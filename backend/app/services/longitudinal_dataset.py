"""Leak-resistant patient timeline construction for P0-03."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Any, Iterable, Literal, Mapping
import unicodedata

from app.services.disease_progression import (
    AD_ADAPTER,
    FATTY_LIVER_ADAPTER,
    DiseaseProgressionAdapter,
)


class DatasetValidationError(ValueError):
    """Stable, privacy-safe validation error for a whole dataset build."""

    def __init__(
        self,
        code: str,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class TimelineVisit:
    visit_date: date
    indicators: tuple[dict[str, object], ...]
    patient_age: int | None
    sex: Literal["male", "female"] | None
    input_position: int


@dataclass(frozen=True)
class PatientTimeline:
    adapter: DiseaseProgressionAdapter
    source_dataset: str
    patient_label: str
    group_id: str
    is_synthetic: bool
    source_document: str | None
    import_version: str | None
    final_stage: object | None
    event_dates: dict[str, date]
    visits: tuple[TimelineVisit, ...]


@dataclass(frozen=True)
class ValidationAudit:
    input_row_count: int
    patient_count: int
    reordered_patient_count: int


_ADAPTERS_BY_DISEASE = {
    FATTY_LIVER_ADAPTER.disease_name: FATTY_LIVER_ADAPTER,
    AD_ADAPTER.disease_name: AD_ADAPTER,
}


def _identity_text(value: object, field: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "").strip())
    if not text:
        raise DatasetValidationError(f"missing_{field}")
    return text


def stable_group_id(source_dataset: str, patient_label: str) -> str:
    source = _identity_text(source_dataset, "source_dataset")
    label = _identity_text(patient_label, "patient_label")
    payload = json.dumps(
        [source, label],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"patient.v1.{hashlib.sha256(payload).hexdigest()}"


def _parse_date(value: object, *, missing_code: str, invalid_code: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise DatasetValidationError(missing_code)
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise DatasetValidationError(invalid_code) from exc


def _normalize_age(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 120 else None


def _normalize_sex(value: object) -> Literal["male", "female"] | None:
    text = str(value or "").strip().lower()
    return text if text in {"male", "female"} else None  # type: ignore[return-value]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_event_dates(
    metadata: Mapping[str, object],
    adapter: DiseaseProgressionAdapter,
) -> dict[str, date]:
    raw = metadata.get("event_dates", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise DatasetValidationError("invalid_event_dates")
    unexpected = set(raw) - set(adapter.event_fields)
    if unexpected:
        raise DatasetValidationError(
            "unexpected_event_field",
            {"field_count": len(unexpected)},
        )
    normalized: dict[str, date] = {}
    for field in adapter.event_fields:
        value = raw.get(field)
        if value in (None, ""):
            continue
        normalized[field] = _parse_date(
            value,
            missing_code="invalid_event_date",
            invalid_code="invalid_event_date",
        )
    return normalized


def _consistent_value(
    values: list[object],
    *,
    field: str,
) -> object:
    first = values[0]
    if any(value != first for value in values[1:]):
        raise DatasetValidationError(f"conflicting_{field}")
    return first


def _consistent_non_null(
    values: list[object | None],
    *,
    field: str,
) -> None:
    non_null = [value for value in values if value is not None]
    if non_null and any(value != non_null[0] for value in non_null[1:]):
        raise DatasetValidationError(f"conflicting_{field}")


def rebuild_patient_timelines(
    rows: Iterable[Mapping[str, object]],
) -> tuple[list[PatientTimeline], ValidationAudit]:
    materialized = list(rows)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for input_position, row in enumerate(materialized):
        if not isinstance(row, Mapping):
            raise DatasetValidationError("invalid_case_row")
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            raise DatasetValidationError("invalid_metadata")

        source = _identity_text(metadata.get("source_dataset"), "source_dataset")
        label = _identity_text(row.get("patient_label"), "patient_label")
        disease_name = _identity_text(row.get("disease_name"), "disease_name")
        adapter = _ADAPTERS_BY_DISEASE.get(disease_name)
        if adapter is None:
            raise DatasetValidationError("unsupported_disease")

        if "is_synthetic" not in metadata or metadata.get("is_synthetic") is None:
            raise DatasetValidationError("missing_is_synthetic")
        provenance = metadata.get("is_synthetic")
        if not isinstance(provenance, bool):
            raise DatasetValidationError("invalid_is_synthetic")

        visit_date = _parse_date(
            metadata.get("visit_date"),
            missing_code="missing_visit_date",
            invalid_code="invalid_visit_date",
        )
        raw_indicators = row.get("indicators")
        if raw_indicators is None:
            raw_indicators = []
        if not isinstance(raw_indicators, list):
            raise DatasetValidationError("invalid_indicators")
        indicators = tuple(
            dict(item) for item in raw_indicators if isinstance(item, Mapping)
        )

        grouped.setdefault((source, label), []).append(
            {
                "adapter": adapter,
                "source_dataset": source,
                "patient_label": label,
                "is_synthetic": provenance,
                "source_document": _optional_text(metadata.get("source_document")),
                "import_version": _optional_text(metadata.get("import_version")),
                "final_stage": metadata.get("final_stage"),
                "event_dates": _normalize_event_dates(metadata, adapter),
                "visit": TimelineVisit(
                    visit_date=visit_date,
                    indicators=indicators,
                    patient_age=_normalize_age(metadata.get("patient_age")),
                    sex=_normalize_sex(metadata.get("sex")),
                    input_position=input_position,
                ),
            }
        )

    patients: list[PatientTimeline] = []
    reordered_patient_count = 0
    for (source, label), entries in grouped.items():
        adapters = [entry["adapter"] for entry in entries]
        if any(adapter.dataset != adapters[0].dataset for adapter in adapters[1:]):
            raise DatasetValidationError("conflicting_disease")

        for field in (
            "is_synthetic",
            "source_document",
            "import_version",
            "final_stage",
            "event_dates",
        ):
            _consistent_value([entry[field] for entry in entries], field=field)
        _consistent_non_null(
            [entry["visit"].patient_age for entry in entries],
            field="patient_age",
        )
        _consistent_non_null(
            [entry["visit"].sex for entry in entries],
            field="sex",
        )

        original_visits = [entry["visit"] for entry in entries]
        ordered_visits = sorted(original_visits, key=lambda visit: visit.visit_date)
        if [visit.visit_date for visit in original_visits] != [
            visit.visit_date for visit in ordered_visits
        ]:
            reordered_patient_count += 1
        dates = [visit.visit_date for visit in ordered_visits]
        if len(set(dates)) != len(dates):
            raise DatasetValidationError("duplicate_patient_visit_date")

        first = entries[0]
        patients.append(
            PatientTimeline(
                adapter=first["adapter"],
                source_dataset=source,
                patient_label=label,
                group_id=stable_group_id(source, label),
                is_synthetic=first["is_synthetic"],
                source_document=first["source_document"],
                import_version=first["import_version"],
                final_stage=first["final_stage"],
                event_dates=dict(first["event_dates"]),
                visits=tuple(ordered_visits),
            )
        )

    patients.sort(
        key=lambda patient: (
            patient.adapter.dataset,
            patient.source_dataset,
            patient.patient_label,
        )
    )
    return patients, ValidationAudit(
        input_row_count=len(materialized),
        patient_count=len(patients),
        reordered_patient_count=reordered_patient_count,
    )
