"""Deterministic, prefix-only reference-case profile construction."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import re
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.longitudinal_evidence import ReferenceDataRelease
from app.services.longitudinal_features import sort_visits, summarize_fixed_window_history
from app.services.reference_case_eligibility import (
    ELIGIBILITY_CONFIG_HASH,
    REFERENCE_PROFILE_SCHEMA_VERSION,
    ReferenceEligibilityCandidate,
    evaluate_reference_candidate,
)


class ReferenceCaseWindowWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disease_code: str
    logical_dataset: str
    dataset_release_id: str
    prediction_task: str
    anonymous_case_code: str
    as_of: str
    horizon_days: Literal[365] = 365
    profile_schema_version: str
    age: int | None = None
    sex: str | None = None
    baseline_stage: str | None = None
    visit_count: int = Field(ge=3)
    span_days: int = Field(ge=0)
    outcome_status: str = "unknown"
    outcome_source: str
    outcome_reliability: Literal["low", "medium", "high"]
    is_synthetic: bool
    eligibility_status: Literal["eligible", "excluded"] = "eligible"
    eligibility_config_hash: str
    data_content_sha256: str
    outcome_value: dict[str, Any] = Field(default_factory=dict)
    source_trace: dict[str, Any]
    feature_summary: dict[str, Any]
    measurement_context_summary: dict[str, Any]
    exclusion_reasons: list[str] = Field(default_factory=list)
    timeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    timeline_canonical_json: str


class WindowBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: tuple[ReferenceCaseWindowWrite, ...]
    total_windows: int
    eligible_windows: int
    exclusion_counts: dict[str, int]


class ReferenceIndexError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class WindowBuildStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_dataset: str
    dataset_release_id: str
    data_content_sha256: str
    eligibility_config_hash: str
    total_windows: int = Field(ge=0)
    eligible_windows: int = Field(ge=0)
    inserted: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)


_CONTEXT_KEYS = (
    "source_type", "facility_name", "device_name", "assay_platform", "method",
    "specimen", "scale_version", "assessment_language", "education_years",
    "education_adjusted", "imaging_type",
)
_SOURCE_TRACE_KEYS = (
    "source", "source_system", "registry", "registry_id", "record_id",
    "dataset_row_id", "review_batch_id",
)
_OUTCOME_VALUE_KEYS = (
    "event_type", "event_date", "stage", "cdr", "observed_at",
    "horizon_days",
)


def _safe_short_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (str, date)):
        return str(value).strip()[:200]
    return None


def _safe_source_trace(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: safe
        for key in _SOURCE_TRACE_KEYS
        if (safe := _safe_short_scalar(value.get(key))) not in (None, "")
    }


def _safe_outcome_value(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: safe
        for key in _OUTCOME_VALUE_KEYS
        if (safe := _safe_short_scalar(value.get(key))) not in (None, "")
    }


def _safe_context_summary(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, set[str]] = {key: set() for key in _CONTEXT_KEYS}
    changed: set[str] = set()
    previous: dict[str, str] = {}
    for visit in history:
        context = visit.get("visit_context") if isinstance(visit.get("visit_context"), Mapping) else {}
        for key in _CONTEXT_KEYS:
            value = context.get(key)
            if value in (None, ""):
                continue
            normalized = str(value).strip()[:200]
            values[key].add(normalized)
            if key in previous and previous[key] != normalized:
                changed.add(key)
            previous[key] = normalized
    return {"values": {key: sorted(items) for key, items in values.items() if items}, "changed": sorted(changed)}


def _safe_visit(visit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "visit_date": str(visit.get("visit_date")),
        "indicators": [
            {key: item.get(key) for key in ("name", "value", "unit") if key in item}
            for item in (visit.get("indicators") or [])
            if isinstance(item, Mapping) and item.get("name")
        ],
        "visit_context": {
            key: visit.get("visit_context", {}).get(key)
            for key in _CONTEXT_KEYS
            if isinstance(visit.get("visit_context"), Mapping) and visit.get("visit_context", {}).get(key) not in (None, "")
        },
    }


def build_window_profiles(rows: Sequence[Mapping[str, Any]], disease_code: str, release: ReferenceDataRelease) -> WindowBuildResult:
    from app.services.longitudinal_task_routing import route_outcome_task

    profiles: list[ReferenceCaseWindowWrite] = []
    exclusion_counts: dict[str, int] = {}
    total_windows = 0
    for row in rows:
        if str(row.get("disease_code", "")) != disease_code:
            continue
        ordered = sort_visits([dict(item) for item in (row.get("visits") or [])])
        routed_task = route_outcome_task(disease_code, row.get("baseline_stage"))
        prediction_task = str(row.get("prediction_task") or routed_task.task or "")
        task_compatible = bool(
            row.get("task_compatible", True)
            and prediction_task
            and routed_task.task == prediction_task
        )
        for index in range(2, len(ordered)):
            total_windows += 1
            history = ordered[: index + 1]
            candidate = ReferenceEligibilityCandidate(
                disease_code=disease_code, expected_disease_code=disease_code,
                dataset_release_id=str(row.get("dataset_release_id", "")), expected_release_id=release.dataset_release_id,
                is_synthetic=bool(row.get("is_synthetic", False)), anonymous_case_code=row.get("anonymous_case_code"),
                visit_count=len(history), source_trace=_safe_source_trace(dict(row.get("source_trace") or {})),
                outcome_source=str(row.get("outcome_source", "")), outcome_reliability=str(row.get("outcome_reliability", "low")),
                task_compatible=task_compatible, timeline_valid=bool(row.get("timeline_valid", True)),
            )
            decision = evaluate_reference_candidate(candidate)
            if not decision.eligible:
                for reason in decision.reasons:
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue
            as_of = str(history[-1]["visit_date"])
            safe_history = [_safe_visit(item) for item in history]
            canonical = json.dumps({"anonymous_case_code": candidate.anonymous_case_code, "as_of": as_of, "visits": safe_history}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            feature_summary = summarize_fixed_window_history([dict(item) for item in history])
            first = date.fromisoformat(str(history[0]["visit_date"]))
            last = date.fromisoformat(as_of)
            outcome = _safe_outcome_value(dict(row.get("outcome_value") or {}))
            profiles.append(ReferenceCaseWindowWrite(
                disease_code=disease_code, logical_dataset=release.logical_dataset,
                dataset_release_id=str(release.dataset_release_id), prediction_task=prediction_task,
                anonymous_case_code=str(candidate.anonymous_case_code), as_of=as_of,
                profile_schema_version=(
                    f"{REFERENCE_PROFILE_SCHEMA_VERSION}+"
                    f"{str(release.data_content_sha256)[:12]}"
                ),
                age=row.get("age"), sex=row.get("sex"), baseline_stage=row.get("baseline_stage"),
                visit_count=len(history), span_days=(last - first).days,
                outcome_status=str(row.get("outcome_status", "unknown")), outcome_value=outcome,
                outcome_source=candidate.outcome_source,
                outcome_reliability=candidate.outcome_reliability,
                is_synthetic=candidate.is_synthetic,
                eligibility_config_hash=ELIGIBILITY_CONFIG_HASH,
                data_content_sha256=str(release.data_content_sha256),
                source_trace=_safe_source_trace(candidate.source_trace), feature_summary=feature_summary,
                measurement_context_summary=_safe_context_summary(history),
                timeline_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                timeline_canonical_json=canonical,
            ))
    return WindowBuildResult(profiles=tuple(profiles), total_windows=total_windows, eligible_windows=len(profiles), exclusion_counts=exclusion_counts)


def _metadata(row: Any) -> dict[str, Any]:
    value = getattr(row, "case_metadata", None)
    if value is None and isinstance(row, Mapping):
        value = row.get("case_metadata", row.get("metadata", {}))
    return dict(value) if isinstance(value, Mapping) else {}


def _release_from_metadata(
    metadata_rows: Sequence[Mapping[str, Any]],
    logical_dataset: str,
) -> ReferenceDataRelease:
    scoped = [
        row for row in metadata_rows
        if row.get("logical_dataset", row.get("source_dataset")) == logical_dataset
    ]
    active_ids = {
        str(row.get("dataset_release_id"))
        for row in scoped if row.get("dataset_active") is True
    }
    if len(active_ids) != 1:
        raise ReferenceIndexError(
            "multiple_active_releases" if len(active_ids) > 1
            else "active_release_missing"
        )
    release_id = next(iter(active_ids))
    hashes = {
        str(row.get("data_content_sha256"))
        for row in scoped
        if str(row.get("dataset_release_id")) == release_id
    }
    hashes.discard("None")
    content_hash = next(iter(hashes), "")
    if len(hashes) != 1 or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise ReferenceIndexError("active_release_hash_invalid")
    return ReferenceDataRelease(
        logical_dataset=logical_dataset,
        dataset_release_id=release_id,
        data_content_sha256=content_hash,
    )


def read_active_reference_release(db: Any, logical_dataset: str) -> ReferenceDataRelease:
    """Read only release metadata; never materialize case indicators."""
    from app.db.models import CaseRecord, Disease
    from sqlalchemy import text
    from app.core.config import settings

    should_close_transaction = callable(getattr(db, "rollback", None))
    try:
        execute = getattr(db, "execute", None)
        if callable(execute):
            execute(text(
                f"SET LOCAL statement_timeout = {max(1, int(settings.REFERENCE_CASE_QUERY_TIMEOUT_MS))}"
            ))
        rows = (
            db.query(CaseRecord.case_metadata)
            .join(Disease, CaseRecord.disease_id == Disease.id)
            .filter(Disease.code == logical_dataset)
            .all()
        )
        metadata_rows = []
        for row in rows:
            value = row[0] if isinstance(row, (tuple, list)) else getattr(row, "case_metadata", row)
            metadata_rows.append(dict(value) if isinstance(value, Mapping) else {})
        return _release_from_metadata(metadata_rows, logical_dataset)
    except ReferenceIndexError:
        raise
    except Exception as exc:
        raise ReferenceIndexError("reference_query_failed") from exc
    finally:
        if should_close_transaction:
            db.rollback()


def _load_active_reference_rows_in_transaction(db: Any, logical_dataset: str) -> tuple[ReferenceDataRelease, list[dict[str, Any]]]:
    from app.db.models import CaseRecord, Disease

    try:
        source_rows = (
            db.query(CaseRecord)
            .join(Disease, CaseRecord.disease_id == Disease.id)
            .filter(Disease.code == logical_dataset)
            .all()
        )
    except Exception as exc:
        raise ReferenceIndexError("reference_query_failed") from exc
    metadata_rows = [_metadata(row) for row in source_rows]
    release = _release_from_metadata(metadata_rows, logical_dataset)
    scoped = [row for row in source_rows if _metadata(row).get("logical_dataset", _metadata(row).get("source_dataset")) == logical_dataset]
    release_id = str(release.dataset_release_id)
    disease_code = "ad" if logical_dataset == "ad" else "fatty_liver"
    grouped: dict[str, dict[str, Any]] = {}
    for row in scoped:
        metadata = _metadata(row)
        if str(metadata.get("dataset_release_id")) != release_id:
            continue
        code = getattr(row, "anonymous_case_code", None) or metadata.get("anonymous_case_code")
        if not code:
            continue
        item = grouped.setdefault(str(code), {
            "disease_code": disease_code, "dataset_release_id": release_id,
            "is_synthetic": bool(metadata.get("is_synthetic", False)), "anonymous_case_code": str(code),
            "source_trace": metadata.get("source_trace", {}), "outcome_source": metadata.get("outcome_source", ""),
            "outcome_reliability": metadata.get("outcome_reliability", "low"), "task_compatible": metadata.get("task_compatible", True),
            "timeline_valid": metadata.get("timeline_valid", True), "age": metadata.get("age"), "sex": metadata.get("sex"),
            "baseline_stage": metadata.get("baseline_stage"), "prediction_task": metadata.get("prediction_task"),
            "outcome_status": metadata.get("outcome_status", "unknown"),
            "outcome_value": metadata.get("outcome_value", {}), "visits": [],
        })
        if isinstance(row, Mapping) and isinstance(row.get("visits"), list):
            item["visits"].extend(row["visits"])
        else:
            item["visits"].append({"visit_date": metadata.get("visit_date") or getattr(row, "created_at", None), "indicators": getattr(row, "indicators", None) or metadata.get("indicators", []), "visit_context": metadata.get("visit_context", {})})
    return release, list(grouped.values())


def load_active_reference_rows(db: Any, logical_dataset: str) -> tuple[ReferenceDataRelease, list[dict[str, Any]]]:
    """Read the active release in a bounded transaction and return detached data."""
    should_close_transaction = callable(getattr(db, "rollback", None))
    try:
        execute = getattr(db, "execute", None)
        if callable(execute):
            from sqlalchemy import text
            from app.core.config import settings

            execute(text(
                f"SET LOCAL statement_timeout = {max(1, int(settings.REFERENCE_CASE_QUERY_TIMEOUT_MS))}"
            ))
        return _load_active_reference_rows_in_transaction(db, logical_dataset)
    finally:
        if should_close_transaction:
            db.rollback()


def synchronize_reference_case_windows(db: Any, logical_dataset: str, *, apply: bool = False) -> WindowBuildStatistics:
    from app.db.models import Disease, ReferenceCaseWindow
    from app.services.reference_case_eligibility import ELIGIBILITY_CONFIG_HASH

    release, rows = load_active_reference_rows(db, logical_dataset)
    result = build_window_profiles(rows, logical_dataset, release)
    statistics = WindowBuildStatistics(
        logical_dataset=logical_dataset, dataset_release_id=release.dataset_release_id,
        data_content_sha256=release.data_content_sha256, eligibility_config_hash=ELIGIBILITY_CONFIG_HASH,
        total_windows=result.total_windows, eligible_windows=result.eligible_windows, inserted=0,
        unchanged=0, exclusion_counts=result.exclusion_counts,
    )
    if not apply:
        return statistics
    from sqlalchemy.dialects.postgresql import insert

    values = []
    for profile in result.profiles:
        payload = profile.model_dump(mode="json")
        payload.pop("disease_code", None)
        payload.pop("timeline_canonical_json", None)
        values.append(payload)
    if not values:
        return statistics
    disease = db.query(Disease).filter(Disease.code == logical_dataset).first()
    if disease is None:
        raise ReferenceIndexError("disease_missing")
    for payload in values:
        payload["disease_id"] = int(disease.id)
    statement = insert(ReferenceCaseWindow).values(values).on_conflict_do_nothing(constraint="uq_reference_case_windows_case_version")
    try:
        inserted = max(int(db.execute(statement).rowcount or 0), 0)
    except Exception as exc:
        raise ReferenceIndexError("reference_persistence_failed") from exc
    db.commit()
    return statistics.model_copy(update={"inserted": inserted, "unchanged": result.eligible_windows - inserted})


__all__ = ["ReferenceCaseWindowWrite", "WindowBuildResult", "ReferenceIndexError", "WindowBuildStatistics", "build_window_profiles", "read_active_reference_release", "load_active_reference_rows", "synchronize_reference_case_windows"]
