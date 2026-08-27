"""Versioned longitudinal reference-data release helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class DataReleaseError(ValueError):
    """A stable failure raised before an activity switch is flushed."""


@dataclass(frozen=True)
class DataReleaseSwitchResult:
    logical_dataset: str
    previous_release_id: str | None
    active_release_id: str
    updated_row_count: int


def _metadata(row: Any) -> dict[str, Any]:
    value = row.case_metadata or {}
    return value if isinstance(value, dict) else {}


def _logical_dataset(row: Any) -> str | None:
    value = _metadata(row)
    return value.get("logical_dataset") or value.get("source_dataset")


def select_active_release_rows(
    rows: list[Any],
    logical_dataset: str,
) -> list[Any]:
    """Select one explicit active release, or legacy rows before migration."""

    scoped = [row for row in rows if _logical_dataset(row) == logical_dataset]
    active = [
        row for row in scoped if _metadata(row).get("dataset_active") is True
    ]
    if active:
        return active
    return [row for row in scoped if "dataset_active" not in _metadata(row)]


def activate_data_release(
    db,
    logical_dataset: str,
    release_id: str,
) -> DataReleaseSwitchResult:
    """Switch one logical dataset inside the caller-owned transaction."""

    from app.db.models import CaseRecord

    rows = [
        row
        for row in db.query(CaseRecord).all()
        if _logical_dataset(row) == logical_dataset
    ]
    release_ids = {
        str(_metadata(row).get("dataset_release_id"))
        for row in rows
        if _metadata(row).get("dataset_release_id")
    }
    if release_id not in release_ids:
        raise DataReleaseError("release_missing")

    active_ids = {
        str(_metadata(row).get("dataset_release_id"))
        for row in rows
        if _metadata(row).get("dataset_active") is True
        and _metadata(row).get("dataset_release_id")
    }
    if len(active_ids) > 1:
        raise DataReleaseError("multiple_active_releases")
    previous_release_id = next(iter(active_ids), None)

    for row in rows:
        value = dict(_metadata(row))
        value["logical_dataset"] = logical_dataset
        value["dataset_active"] = value.get("dataset_release_id") == release_id
        row.case_metadata = value
    db.flush()
    return DataReleaseSwitchResult(
        logical_dataset=logical_dataset,
        previous_release_id=previous_release_id,
        active_release_id=release_id,
        updated_row_count=len(rows),
    )
