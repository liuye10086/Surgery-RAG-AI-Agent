"""Leak-resistant patient timeline construction for P0-03."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
from typing import Any, Iterable, Literal, Mapping
import unicodedata

from app.services.disease_progression import (
    AD_ADAPTER,
    FATTY_LIVER_ADAPTER,
    DiseaseProgressionAdapter,
)
from app.schemas.longitudinal_dataset import (
    CohortCounts,
    CurrentState,
    DatasetAuditSummary,
    DiseaseDatasetSummary,
    FixedWindowSample,
    HistoricalFeatures,
    LabelAudit,
    SampleIdentity,
    TargetEvent,
)
from app.services.longitudinal_features import (
    build_prefixes,
    summarize_fixed_window_history,
)


HORIZON_DAYS = 365
MINIMUM_VISITS = 3


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


@dataclass(frozen=True)
class TargetContext:
    current_state: CurrentState
    target_event: TargetEvent


@dataclass(frozen=True)
class DatasetBuildResult:
    real_train: tuple[FixedWindowSample, ...]
    real_audit: tuple[FixedWindowSample, ...]
    synthetic_audit: tuple[FixedWindowSample, ...]
    summary: DatasetAuditSummary


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


def resolve_target(patient: PatientTimeline, as_of: date) -> TargetContext:
    """Resolve the task state using dated events known by ``as_of`` only."""
    if patient.adapter.dataset == "fatty_liver":
        hcc_date = patient.event_dates.get("hcc_date")
        cirrhosis_date = patient.event_dates.get("cirrhosis_date")
        if hcc_date is not None and hcc_date <= as_of:
            return TargetContext(current_state="hcc", target_event="none")
        if cirrhosis_date is not None and cirrhosis_date <= as_of:
            return TargetContext(current_state="cirrhosis", target_event="hcc")
        return TargetContext(
            current_state="pre_cirrhosis",
            target_event="cirrhosis_or_hcc",
        )

    if patient.adapter.dataset == "ad":
        dementia_date = patient.event_dates.get("dementia_date")
        if dementia_date is not None and dementia_date <= as_of:
            return TargetContext(current_state="dementia", target_event="none")
        return TargetContext(
            current_state="pre_dementia",
            target_event="dementia",
        )

    raise DatasetValidationError("unsupported_disease")


def _eligible_target_events(
    patient: PatientTimeline,
    target: TargetContext,
) -> list[tuple[str, date]]:
    if target.target_event == "cirrhosis_or_hcc":
        fields = ("cirrhosis_date", "hcc_date")
    elif target.target_event == "hcc":
        fields = ("hcc_date",)
    elif target.target_event == "dementia":
        fields = ("dementia_date",)
    else:
        fields = ()
    return sorted(
        (
            (field, patient.event_dates[field])
            for field in fields
            if field in patient.event_dates
        ),
        key=lambda item: (item[1], item[0]),
    )


def _reached_event(
    patient: PatientTimeline,
    target: TargetContext,
) -> tuple[str, date]:
    if target.current_state == "hcc":
        return "hcc_date", patient.event_dates["hcc_date"]
    if target.current_state == "dementia":
        return "dementia_date", patient.event_dates["dementia_date"]
    raise DatasetValidationError("target_state_inconsistent")


def _final_proves_undated_progression(
    patient: PatientTimeline,
    target: TargetContext,
    eligible_events: list[tuple[str, date]],
) -> bool:
    if eligible_events:
        return False
    final = patient.final_stage
    if patient.adapter.dataset == "fatty_liver":
        final_text = str(final or "").strip()
        if target.target_event == "cirrhosis_or_hcc":
            return final_text in {"cirrhosis", "hcc"}
        if target.target_event == "hcc":
            return final_text == "hcc"
        return False
    if patient.adapter.dataset == "ad":
        try:
            return float(final) >= 1
        except (TypeError, ValueError):
            return False
    return False


def label_fixed_window(patient: PatientTimeline, as_of: date) -> LabelAudit:
    """Label the fixed interval ``(as_of, as_of + 365 days]``."""
    target = resolve_target(patient, as_of)
    window_start = as_of + timedelta(days=1)
    window_end = as_of + timedelta(days=HORIZON_DAYS)
    last_followup = max(visit.visit_date for visit in patient.visits)

    if target.target_event == "none":
        event_type, event_date = _reached_event(patient, target)
        return LabelAudit(
            status="not_applicable",
            training_label=None,
            reason_code="target_already_reached",
            window_start=window_start,
            window_end=window_end,
            target_event="none",
            event_type=event_type,
            event_date=event_date,
            last_followup_date=last_followup,
        )

    eligible_events = [
        event
        for event in _eligible_target_events(patient, target)
        if event[1] > as_of
    ]
    earliest = eligible_events[0] if eligible_events else None
    if earliest is not None and earliest[1] <= window_end:
        return LabelAudit(
            status="positive",
            training_label=1,
            reason_code="target_event_within_window",
            window_start=window_start,
            window_end=window_end,
            target_event=target.target_event,
            event_type=earliest[0],
            event_date=earliest[1],
            last_followup_date=last_followup,
        )

    if _final_proves_undated_progression(patient, target, eligible_events):
        return LabelAudit(
            status="insufficient_observation",
            training_label=None,
            reason_code="progressed_without_target_date",
            window_start=window_start,
            window_end=window_end,
            target_event=target.target_event,
            event_type=None,
            event_date=None,
            last_followup_date=last_followup,
        )

    if earliest is not None:
        return LabelAudit(
            status="negative",
            training_label=0,
            reason_code="target_event_after_window",
            window_start=window_start,
            window_end=window_end,
            target_event=target.target_event,
            event_type=earliest[0],
            event_date=earliest[1],
            last_followup_date=last_followup,
        )

    if last_followup >= window_end:
        return LabelAudit(
            status="negative",
            training_label=0,
            reason_code="full_window_observed_without_event",
            window_start=window_start,
            window_end=window_end,
            target_event=target.target_event,
            event_type=None,
            event_date=None,
            last_followup_date=last_followup,
        )

    return LabelAudit(
        status="insufficient_observation",
        training_label=None,
        reason_code="followup_ends_before_window",
        window_start=window_start,
        window_end=window_end,
        target_event=target.target_event,
        event_type=None,
        event_date=None,
        last_followup_date=last_followup,
    )


_FORBIDDEN_FEATURE_FIELDS = {
    "final_stage",
    "confirmed",
    "event_dates",
    "cirrhosis_date",
    "hcc_date",
    "dementia_date",
    "fatty_liver_date",
    "last_followup_date",
    "lost_to_followup",
    "total_visits",
    "visit_index",
    "cohort_group",
    "outcome_source",
    "assigned_final_stage",
    "inferred_stage",
    "source_dataset",
    "patient_label",
    "group_id",
    "is_synthetic",
    "label",
    "label_reason",
    "reason_code",
}


def _normalized_feature_key(value: object) -> str:
    return unicodedata.normalize("NFC", str(value)).strip().lower()


def assert_feature_namespace_safe(features: Mapping[str, object]) -> None:
    """Reject outcome, identity, provenance, and audit keys recursively."""

    def inspect(value: object) -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                key = _normalized_feature_key(raw_key)
                if key in _FORBIDDEN_FEATURE_FIELDS:
                    raise DatasetValidationError(
                        "forbidden_feature_field",
                        {"field_count": 1},
                    )
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)

    inspect(features)


def _prefix_visit_dict(visit: TimelineVisit) -> dict[str, object]:
    return {
        "visit_date": visit.visit_date.isoformat(),
        "indicators": [dict(indicator) for indicator in visit.indicators],
    }


def _latest_demographics(
    visits: tuple[TimelineVisit, ...],
) -> tuple[int | None, Literal["male", "female"] | None]:
    age = next(
        (
            visit.patient_age
            for visit in reversed(visits)
            if visit.patient_age is not None
        ),
        None,
    )
    sex = next(
        (visit.sex for visit in reversed(visits) if visit.sex is not None),
        None,
    )
    return age, sex


def _sample_sort_key(sample: FixedWindowSample) -> tuple[object, ...]:
    identity = sample.identity
    return (
        identity.disease,
        identity.source_dataset,
        identity.patient_label,
        identity.as_of,
    )


def _empty_counts() -> CohortCounts:
    return CohortCounts(
        patient_count=0,
        candidate_patient_count=0,
        trainable_patient_count=0,
        visit_count=0,
        candidate_count=0,
        positive_count=0,
        negative_count=0,
        insufficient_observation_count=0,
        not_applicable_count=0,
        trainable_count=0,
        label_reason_counts={},
    )


def _cohort_counts(
    patients: list[PatientTimeline],
    samples: list[FixedWindowSample],
) -> CohortCounts:
    status_counts = Counter(sample.label.status for sample in samples)
    reason_counts = Counter(sample.label.reason_code for sample in samples)
    candidate_groups = {sample.identity.group_id for sample in samples}
    trainable_groups = {
        sample.identity.group_id
        for sample in samples
        if sample.label.status in {"positive", "negative"}
    }
    return CohortCounts(
        patient_count=len(patients),
        candidate_patient_count=len(candidate_groups),
        trainable_patient_count=len(trainable_groups),
        visit_count=sum(len(patient.visits) for patient in patients),
        candidate_count=len(samples),
        positive_count=status_counts["positive"],
        negative_count=status_counts["negative"],
        insufficient_observation_count=status_counts[
            "insufficient_observation"
        ],
        not_applicable_count=status_counts["not_applicable"],
        trainable_count=(
            status_counts["positive"] + status_counts["negative"]
        ),
        label_reason_counts=dict(sorted(reason_counts.items())),
    )


def _patient_was_reordered(patient: PatientTimeline) -> bool:
    positions = [visit.input_position for visit in patient.visits]
    return positions != sorted(positions)


def build_fixed_window_dataset(
    rows: Iterable[Mapping[str, object]],
) -> DatasetBuildResult:
    """Build formal real training rows plus complete real/synthetic audits."""
    patients, _ = rebuild_patient_timelines(rows)
    real_audit: list[FixedWindowSample] = []
    synthetic_audit: list[FixedWindowSample] = []

    for patient in patients:
        visit_dicts = [_prefix_visit_dict(visit) for visit in patient.visits]
        prefixes = build_prefixes(visit_dicts, minimum_visits=MINIMUM_VISITS)
        for prefix_index, prefix in enumerate(prefixes, start=MINIMUM_VISITS):
            prefix_visits = patient.visits[:prefix_index]
            as_of = date.fromisoformat(str(prefix["as_of"]))
            target = resolve_target(patient, as_of)
            label = label_fixed_window(patient, as_of)
            history = summarize_fixed_window_history(prefix["visits"])
            age, sex = _latest_demographics(prefix_visits)
            features = HistoricalFeatures(
                age=age,
                sex=sex,
                visit_count=history["visit_count"],
                observation_span_days=history["observation_span_days"],
                days_since_previous_visit=history["days_since_previous_visit"],
                indicators=history["indicators"],
            )
            assert_feature_namespace_safe(features.model_dump(mode="json"))
            sample = FixedWindowSample(
                identity=SampleIdentity(
                    disease=patient.adapter.dataset,
                    disease_name=patient.adapter.disease_name,
                    source_dataset=patient.source_dataset,
                    patient_label=patient.patient_label,
                    group_id=patient.group_id,
                    is_synthetic=patient.is_synthetic,
                    source_document=patient.source_document,
                    import_version=patient.import_version,
                    as_of=as_of,
                    current_state=target.current_state,
                    target_event=target.target_event,
                    history_visit_count=len(prefix_visits),
                    history_start=prefix_visits[0].visit_date,
                ),
                features=features,
                label=label,
            )
            if patient.is_synthetic:
                synthetic_audit.append(sample)
            else:
                real_audit.append(sample)

    real_audit.sort(key=_sample_sort_key)
    synthetic_audit.sort(key=_sample_sort_key)
    real_train = sorted(
        (
            sample
            for sample in real_audit
            if sample.label.status in {"positive", "negative"}
        ),
        key=_sample_sort_key,
    )

    disease_summaries: dict[str, DiseaseDatasetSummary] = {}
    for adapter in (FATTY_LIVER_ADAPTER, AD_ADAPTER):
        disease_patients = [
            patient
            for patient in patients
            if patient.adapter.dataset == adapter.dataset
        ]
        real_patients = [
            patient for patient in disease_patients if not patient.is_synthetic
        ]
        synthetic_patients = [
            patient for patient in disease_patients if patient.is_synthetic
        ]
        disease_real_samples = [
            sample
            for sample in real_audit
            if sample.identity.disease == adapter.dataset
        ]
        disease_synthetic_samples = [
            sample
            for sample in synthetic_audit
            if sample.identity.disease == adapter.dataset
        ]
        disease_summaries[adapter.dataset] = DiseaseDatasetSummary(
            disease=adapter.dataset,
            disease_name=adapter.disease_name,
            source_datasets=sorted(
                {patient.source_dataset for patient in disease_patients}
            ),
            real=(
                _cohort_counts(real_patients, disease_real_samples)
                if real_patients or disease_real_samples
                else _empty_counts()
            ),
            synthetic=(
                _cohort_counts(synthetic_patients, disease_synthetic_samples)
                if synthetic_patients or disease_synthetic_samples
                else _empty_counts()
            ),
            reordered_patient_count=sum(
                _patient_was_reordered(patient) for patient in disease_patients
            ),
        )

    return DatasetBuildResult(
        real_train=tuple(real_train),
        real_audit=tuple(real_audit),
        synthetic_audit=tuple(synthetic_audit),
        summary=DatasetAuditSummary(diseases=disease_summaries),
    )
