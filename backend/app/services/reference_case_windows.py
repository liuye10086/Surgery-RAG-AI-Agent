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
    sex: Literal["male", "female"] | None = None
    baseline_stage: str | None = None
    visit_count: int = Field(ge=3)
    span_days: int = Field(ge=0)
    outcome_status: Literal["positive", "negative", "unknown", "not_observed"] = "unknown"
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

REFERENCE_DATASETS = {
    "fatty_liver": "longitudinal_300",
    "ad": "ad_longitudinal_300",
}


def resolve_reference_dataset(selector: str) -> tuple[str, str]:
    """Resolve the public disease selector to the importer's dataset identity."""
    normalized = str(selector).strip()
    if normalized in REFERENCE_DATASETS:
        return normalized, REFERENCE_DATASETS[normalized]
    for disease_code, logical_dataset in REFERENCE_DATASETS.items():
        if normalized == logical_dataset:
            return disease_code, logical_dataset
    raise ReferenceIndexError("reference_dataset_unsupported")


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
    by_indicator: dict[str, dict[str, Any]] = {}
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
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, Mapping):
                continue
            name = str(indicator.get("name") or "").strip().casefold()
            if not name:
                continue
            by_indicator[name] = {
                key: context.get(key)
                for key in _CONTEXT_KEYS
                if context.get(key) not in (None, "")
            }
    return {
        "values": {key: sorted(items) for key, items in values.items() if items},
        "changed": sorted(changed),
        "by_indicator": by_indicator,
    }


def summarize_measurement_context(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build the privacy-bounded context shape shared by both comparison sides."""
    return _safe_context_summary(history)


def _date_or_none(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _latest_indicator_value(history: Sequence[Mapping[str, Any]], name: str) -> float | None:
    for visit in reversed(history):
        for indicator in visit.get("indicators") or []:
            if str(indicator.get("name") or "").strip().casefold() != name.casefold():
                continue
            try:
                return float(indicator.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _window_baseline_stage(
    disease_code: str,
    row: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    as_of: date,
) -> str | None:
    event_dates = row.get("event_dates") if isinstance(row.get("event_dates"), Mapping) else {}
    if disease_code == "fatty_liver" and event_dates:
        hcc_date = _date_or_none(event_dates.get("hcc_date"))
        cirrhosis_date = _date_or_none(event_dates.get("cirrhosis_date"))
        if hcc_date and hcc_date <= as_of:
            return "hcc"
        if cirrhosis_date and cirrhosis_date <= as_of:
            return "cirrhosis"
        return "pre_cirrhosis"
    if disease_code == "ad" and row.get("baseline_stage") in (None, ""):
        cdr = _latest_indicator_value(history, "cdr")
        if cdr is not None:
            return "dementia" if cdr >= 1 else "mci" if cdr > 0 else "normal"
    return row.get("baseline_stage")


def _window_outcome(
    disease_code: str,
    prediction_task: str,
    row: Mapping[str, Any],
    as_of: date,
) -> tuple[str, str, str, dict[str, Any]]:
    """Return only an audited outcome observed inside ``(as_of, as_of+365d]``."""
    if row.get("outcome_source"):
        supplied = _safe_outcome_value(dict(row.get("outcome_value") or {}))
        event_date = _date_or_none(supplied.get("event_date"))
        if event_date and as_of < event_date <= as_of + timedelta(days=365):
            return (
                str(row.get("outcome_status", "positive")),
                str(row["outcome_source"]),
                str(row.get("outcome_reliability", "low")),
                supplied,
            )
        return "unknown", "outcome_not_observed", "low", {"horizon_days": 365}
    event_dates = row.get("event_dates") if isinstance(row.get("event_dates"), Mapping) else {}
    if prediction_task == "fatty_liver.pre_cirrhosis_to_progression":
        event_type, event_key, source = "cirrhosis", "cirrhosis_date", "explicit_cirrhosis"
    elif prediction_task == "fatty_liver.cirrhosis_to_hcc":
        event_type, event_key, source = "hcc", "hcc_date", "explicit_hcc"
    elif prediction_task == "ad.pre_dementia_to_dementia":
        event_type, event_key, source = "dementia", "dementia_date", "explicit_cdr"
    else:
        return "unknown", "outcome_not_observed", "low", {"horizon_days": 365}
    event_date = _date_or_none(event_dates.get(event_key))
    if event_date and as_of < event_date <= as_of + timedelta(days=365):
        return (
            "positive", source, "high",
            {"event_type": event_type, "event_date": event_date.isoformat(), "horizon_days": 365},
        )
    return "unknown", "outcome_not_observed", "low", {"horizon_days": 365}


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
        dates = [str(item.get("visit_date")) for item in ordered]
        timeline_valid = bool(row.get("timeline_valid", True) and len(dates) == len(set(dates)))
        try:
            from app.services.indicator_validation import validate_visits

            validate_visits(disease_code, ordered)
        except Exception:
            timeline_valid = False
        for index in range(2, len(ordered)):
            total_windows += 1
            history = ordered[: index + 1]
            as_of_date = date.fromisoformat(str(history[-1]["visit_date"]))
            baseline_stage = _window_baseline_stage(
                disease_code, row, history, as_of_date,
            )
            routed_task = route_outcome_task(disease_code, baseline_stage)
            prediction_task = str(row.get("prediction_task") or routed_task.task or "")
            task_compatible = bool(
                row.get("task_compatible", True)
                and prediction_task
                and routed_task.task == prediction_task
            )
            outcome_status, outcome_source, outcome_reliability, outcome = _window_outcome(
                disease_code, prediction_task, row, as_of_date,
            )
            candidate = ReferenceEligibilityCandidate(
                disease_code=disease_code, expected_disease_code=disease_code,
                dataset_release_id=str(row.get("dataset_release_id", "")), expected_release_id=release.dataset_release_id,
                is_synthetic=bool(row.get("is_synthetic", False)), anonymous_case_code=row.get("anonymous_case_code"),
                visit_count=len(history), source_trace=_safe_source_trace(dict(row.get("source_trace") or {})),
                outcome_source=outcome_source, outcome_reliability=outcome_reliability,
                task_compatible=task_compatible, timeline_valid=timeline_valid,
            )
            decision = evaluate_reference_candidate(candidate)
            if not decision.eligible:
                for reason in decision.reasons:
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            # Invalid/missing anonymous codes cannot satisfy the storage CHECK;
            # count their exclusion but do not create an unpersistable profile.
            if not candidate.anonymous_case_code or not re.fullmatch(
                r"CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}",
                candidate.anonymous_case_code,
            ):
                continue
            as_of = str(history[-1]["visit_date"])
            safe_history = [_safe_visit(item) for item in history]
            canonical = json.dumps({"anonymous_case_code": candidate.anonymous_case_code, "as_of": as_of, "visits": safe_history}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            feature_summary = summarize_fixed_window_history([dict(item) for item in history])
            first = date.fromisoformat(str(history[0]["visit_date"]))
            last = date.fromisoformat(as_of)
            profiles.append(ReferenceCaseWindowWrite(
                disease_code=disease_code, logical_dataset=release.logical_dataset,
                dataset_release_id=str(release.dataset_release_id), prediction_task=prediction_task,
                anonymous_case_code=str(candidate.anonymous_case_code), as_of=as_of,
                profile_schema_version=(
                    f"{REFERENCE_PROFILE_SCHEMA_VERSION}+"
                    f"{str(release.data_content_sha256)[:12]}"
                ),
                age=row.get("age"), sex=row.get("sex"), baseline_stage=baseline_stage or "unknown",
                visit_count=len(history), span_days=(last - first).days,
                outcome_status=outcome_status, outcome_value=outcome,
                outcome_source=candidate.outcome_source,
                outcome_reliability=candidate.outcome_reliability,
                is_synthetic=candidate.is_synthetic,
                eligibility_status="eligible" if decision.eligible else "excluded",
                eligibility_config_hash=ELIGIBILITY_CONFIG_HASH,
                data_content_sha256=str(release.data_content_sha256),
                source_trace=_safe_source_trace(candidate.source_trace), feature_summary=feature_summary,
                measurement_context_summary=_safe_context_summary(history),
                exclusion_reasons=list(decision.reasons),
                timeline_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                timeline_canonical_json=canonical,
            ))
    return WindowBuildResult(
        profiles=tuple(profiles), total_windows=total_windows,
        eligible_windows=sum(profile.eligibility_status == "eligible" for profile in profiles),
        exclusion_counts=exclusion_counts,
    )


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


def read_active_reference_release(db: Any, selector: str) -> ReferenceDataRelease:
    """Read only release metadata; never materialize case indicators."""
    from app.db.models import CaseRecord, Disease
    from sqlalchemy import text
    from app.core.config import settings

    disease_code, logical_dataset = resolve_reference_dataset(selector)
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
            .filter(Disease.code == disease_code)
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


def _group_active_source_rows(
    source_rows: Sequence[Any],
    disease_code: str,
    logical_dataset: str,
    release: ReferenceDataRelease,
) -> list[dict[str, Any]]:
    scoped = [
        row for row in source_rows
        if _metadata(row).get("logical_dataset", _metadata(row).get("source_dataset")) == logical_dataset
        and str(_metadata(row).get("dataset_release_id")) == str(release.dataset_release_id)
    ]
    grouped: dict[str, dict[str, Any]] = {}
    for row in scoped:
        metadata = _metadata(row)
        code = getattr(row, "anonymous_case_code", None) or metadata.get("anonymous_case_code")
        if not code:
            continue
        row_id = getattr(row, "id", None)
        supplied_trace = metadata.get("source_trace") if isinstance(metadata.get("source_trace"), Mapping) else {}
        source_trace = dict(supplied_trace)
        if not source_trace:
            source_trace = {
                "source_system": "source_document" if metadata.get("source_document") else "approved_data_release",
                "registry_id": str(release.dataset_release_id),
                "record_id": row_id,
            }
        item = grouped.setdefault(str(code), {
            "disease_code": disease_code,
            "dataset_release_id": str(release.dataset_release_id),
            "is_synthetic": bool(metadata.get("is_synthetic", False)),
            "anonymous_case_code": str(code),
            "source_trace": _safe_source_trace(source_trace),
            "outcome_source": metadata.get("outcome_source"),
            "outcome_reliability": metadata.get("outcome_reliability", "low"),
            "task_compatible": metadata.get("task_compatible", True),
            "timeline_valid": metadata.get("timeline_valid", True),
            "age": metadata.get("patient_age", metadata.get("age")),
            "sex": metadata.get("sex"),
            "baseline_stage": metadata.get("baseline_stage"),
            "prediction_task": metadata.get("prediction_task"),
            "outcome_status": metadata.get("outcome_status", "unknown"),
            "outcome_value": metadata.get("outcome_value", {}),
            "event_dates": dict(metadata.get("event_dates") or {}),
            "final_stage": metadata.get("final_stage"),
            "visits": [],
        })
        if isinstance(row, Mapping) and isinstance(row.get("visits"), list):
            item["visits"].extend(row["visits"])
        else:
            visit_date = metadata.get("visit_date")
            if not visit_date:
                item["timeline_valid"] = False
                continue
            item["visits"].append({
                "visit_date": visit_date,
                "indicators": getattr(row, "indicators", None) or metadata.get("indicators", []),
                "visit_context": metadata.get("visit_context", {}),
            })
    return list(grouped.values())


def _load_active_reference_rows_in_transaction(db: Any, selector: str) -> tuple[ReferenceDataRelease, list[dict[str, Any]]]:
    from app.db.models import CaseRecord, Disease

    disease_code, logical_dataset = resolve_reference_dataset(selector)

    try:
        source_rows = (
            db.query(CaseRecord)
            .join(Disease, CaseRecord.disease_id == Disease.id)
            .filter(Disease.code == disease_code)
            .all()
        )
    except Exception as exc:
        raise ReferenceIndexError("reference_query_failed") from exc
    metadata_rows = [_metadata(row) for row in source_rows]
    release = _release_from_metadata(metadata_rows, logical_dataset)
    return release, _group_active_source_rows(
        source_rows, disease_code, logical_dataset, release,
    )


def load_active_reference_rows(db: Any, selector: str) -> tuple[ReferenceDataRelease, list[dict[str, Any]]]:
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
        return _load_active_reference_rows_in_transaction(db, selector)
    finally:
        if should_close_transaction:
            db.rollback()


def synchronize_reference_case_windows(db: Any, selector: str, *, apply: bool = False) -> WindowBuildStatistics:
    from app.db.models import Disease, ReferenceCaseWindow
    from app.services.reference_case_eligibility import ELIGIBILITY_CONFIG_HASH

    disease_code, logical_dataset = resolve_reference_dataset(selector)
    release, rows = load_active_reference_rows(db, selector)
    result = build_window_profiles(rows, disease_code, release)
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
    disease = db.query(Disease).filter(Disease.code == disease_code).first()
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


__all__ = [
    "REFERENCE_DATASETS", "ReferenceCaseWindowWrite", "WindowBuildResult",
    "ReferenceIndexError", "WindowBuildStatistics", "build_window_profiles",
    "read_active_reference_release", "load_active_reference_rows",
    "resolve_reference_dataset", "summarize_measurement_context",
    "synchronize_reference_case_windows",
]
