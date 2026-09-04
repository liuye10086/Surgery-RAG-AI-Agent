"""Canonicalization and integrity helpers for EvidenceBundle v1."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4
from uuid import UUID

from app.schemas.longitudinal_evidence import (
    EvidenceBundle,
    ReferenceCaseEvidence,
    ReferenceDataRelease,
    ReferencePoolStatistics,
    ReferenceCaseFeatureProfile,
    ReferenceCaseProfile,
    ReferenceCaseScoreBreakdown,
)
from app.services.reference_case_eligibility import ELIGIBILITY_CONFIG_HASH
from app.services.reference_case_similarity import (
    CORE_INDICATORS,
    MAX_CANDIDATES,
    SIMILARITY_CONFIG_HASH,
    canonical_indicator_name,
    score_reference_candidates,
)
from app.services.standard_evidence import StandardEvidenceError, StandardVersionToken, build_standard_evidence, preflight_standard


@dataclass(frozen=True)
class EvidenceVersionToken:
    standard: StandardVersionToken
    dataset_release_id: str | None
    data_content_sha256: str | None
    eligibility_config_hash: str
    similarity_config_hash: str
    logical_dataset: str | None = None
    reference_status: Literal["reference_query_failed", "reference_index_stale"] | None = None


class EvidenceBuildError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EvidenceBuildResult:
    bundle: EvidenceBundle
    evidence_status: Literal["complete", "partial"]
    sources_projection: tuple[dict[str, Any], ...]


def canonicalize_evidence_bundle(bundle: EvidenceBundle) -> bytes:
    payload = bundle.model_dump(mode="json")
    payload["integrity"]["evidence_snapshot_sha256"] = None
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def finalize_evidence_bundle(bundle: EvidenceBundle) -> EvidenceBundle:
    digest = hashlib.sha256(canonicalize_evidence_bundle(bundle)).hexdigest()
    integrity = bundle.integrity.model_copy(update={"evidence_snapshot_sha256": digest})
    return bundle.model_copy(update={"integrity": integrity})


def verify_evidence_bundle(bundle: EvidenceBundle) -> bool:
    declared = bundle.integrity.evidence_snapshot_sha256
    if declared is None:
        return False
    actual = hashlib.sha256(canonicalize_evidence_bundle(bundle)).hexdigest()
    return hmac.compare_digest(declared, actual)


def preflight_evidence_versions(db: Any, disease_id: int, disease_code: str) -> EvidenceVersionToken:
    try:
        standard = preflight_standard(db, disease_id, disease_code)
    except StandardEvidenceError as exc:
        raise EvidenceBuildError(exc.code) from exc
    try:
        from app.services.reference_case_windows import read_active_reference_release

        release = read_active_reference_release(db, disease_code)
        return EvidenceVersionToken(
            standard, release.dataset_release_id, release.data_content_sha256,
            ELIGIBILITY_CONFIG_HASH, SIMILARITY_CONFIG_HASH,
            logical_dataset=release.logical_dataset,
        )
    except Exception as exc:
        code = getattr(exc, "code", "reference_query_failed")
        status = (
            "reference_query_failed"
            if code in {"reference_query_failed", "reference_persistence_failed"}
            else "reference_index_stale"
        )
        return EvidenceVersionToken(
            standard, None, None, ELIGIBILITY_CONFIG_HASH,
            SIMILARITY_CONFIG_HASH, reference_status=status,
        )


def read_version_token(db: Any, disease_code: str, disease_id: int | None = None) -> EvidenceVersionToken:
    if disease_id is None:
        from app.db.models import Disease
        disease = db.query(Disease).filter(Disease.code == disease_code).first()
        if disease is None:
            raise EvidenceBuildError("standard_missing")
        disease_id = int(disease.id)
    return preflight_evidence_versions(db, int(disease_id), disease_code)


def _query_reference_windows_in_transaction(
    db: Any,
    snapshot: Mapping[str, Any],
    token: EvidenceVersionToken,
    standard: Any | None = None,
) -> ReferenceCaseEvidence:
    from app.db.models import ReferenceCaseWindow
    from app.services.longitudinal_features import summarize_fixed_window_history
    from app.services.reference_case_windows import summarize_measurement_context

    disease_id = int(snapshot.get("disease_id") or 0)
    release = ReferenceDataRelease(
        logical_dataset=token.logical_dataset or str(snapshot.get("disease_code", "")),
        dataset_release_id=token.dataset_release_id,
        data_content_sha256=token.data_content_sha256,
    )
    if token.reference_status is not None:
        return ReferenceCaseEvidence(
            status=token.reference_status,
            data_release=release,
            algorithm_version="reference_similarity.v1",
            configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(
                total_windows=0, eligible_windows=0,
                comparable_windows=0, returned_windows=0,
            ),
        )
    from app.services.longitudinal_task_routing import route_outcome_task

    model_options = snapshot.get("model_options")
    requested_task = model_options.get("prediction_task") if isinstance(model_options, Mapping) else None
    routed = route_outcome_task(str(snapshot.get("disease_code", "")), snapshot.get("baseline_stage"))
    prediction_task = str(snapshot.get("prediction_task") or requested_task or routed.task or "unavailable")
    visits = list(snapshot.get("visits") or [])
    summary = summarize_fixed_window_history(visits)
    if standard is not None:
        indicators = {
            key: dict(value)
            for key, value in (summary.get("indicators") or {}).items()
        }
        for rule in getattr(standard, "rules", ()) or ():
            if getattr(rule, "status", None) != "calculable":
                continue
            rule_name = canonical_indicator_name(getattr(rule, "indicator", ""))
            raw_name = next(
                (name for name in indicators if canonical_indicator_name(name) == rule_name),
                None,
            )
            if raw_name is None or str(indicators[raw_name].get("unit") or "") != str(getattr(rule, "unit", None) or ""):
                continue
            indicators[raw_name].update({
                "lower": getattr(rule, "lower", None),
                "upper": getattr(rule, "upper", None),
            })
        summary = {**summary, "indicators": indicators}
    base = db.query(ReferenceCaseWindow).filter(
        ReferenceCaseWindow.disease_id == disease_id,
        ReferenceCaseWindow.logical_dataset == release.logical_dataset,
        ReferenceCaseWindow.dataset_release_id == token.dataset_release_id,
        ReferenceCaseWindow.data_content_sha256 == token.data_content_sha256,
        ReferenceCaseWindow.eligibility_config_hash == token.eligibility_config_hash,
    )
    total = int(base.count())
    if total == 0:
        return ReferenceCaseEvidence(
            status="reference_index_stale", data_release=release,
            algorithm_version="reference_similarity.v1", configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(total_windows=0, eligible_windows=0, comparable_windows=0, returned_windows=0),
        )
    eligible_query = base.filter(
        ReferenceCaseWindow.eligibility_status == "eligible",
        ReferenceCaseWindow.prediction_task == prediction_task,
    )
    eligible_total = int(eligible_query.count())
    exclusion_counts: dict[str, int] = {}
    try:
        from sqlalchemy import text

        exclusion_rows = db.execute(text(
            "SELECT reason, COUNT(*) AS count FROM reference_case_windows "
            "CROSS JOIN LATERAL jsonb_array_elements_text(exclusion_reasons) AS reason "
            "WHERE disease_id=:disease_id AND dataset_release_id=:release_id "
            "AND data_content_sha256=:content_hash AND eligibility_config_hash=:config_hash "
            "AND eligibility_status='excluded' GROUP BY reason ORDER BY reason"
        ), {
            "disease_id": disease_id, "release_id": token.dataset_release_id,
            "content_hash": token.data_content_sha256,
            "config_hash": token.eligibility_config_hash,
        }).mappings().all()
        exclusion_counts = {str(row["reason"]): int(row["count"]) for row in exclusion_rows}
    except (AttributeError, TypeError):
        # Lightweight unit-test doubles may not implement SQL result mappings.
        exclusion_counts = {}
    if eligible_total == 0:
        return ReferenceCaseEvidence(
            status="no_eligible_cases", data_release=release,
            algorithm_version="reference_similarity.v1", configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(
                total_windows=total, eligible_windows=0, comparable_windows=0,
                returned_windows=0, exclusion_counts=exclusion_counts,
            ),
        )
    disease_core = CORE_INDICATORS.get(str(snapshot.get("disease_code", "")), frozenset())
    current_indicators = sorted(
        name for name in (summary.get("indicators") or {})
        if canonical_indicator_name(name) in disease_core
    )
    if current_indicators:
        from sqlalchemy.dialects import postgresql

        eligible_query = eligible_query.filter(
            ReferenceCaseWindow.feature_summary["indicators"].op("?|")(
                postgresql.array(current_indicators)
            )
        )
    else:
        return ReferenceCaseEvidence(
            status="insufficient_comparability", data_release=release,
            algorithm_version="reference_similarity.v1", configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(
                total_windows=total, eligible_windows=eligible_total,
                comparable_windows=0, returned_windows=0,
                exclusion_counts=exclusion_counts,
            ),
        )
    rows = eligible_query.order_by(ReferenceCaseWindow.id.asc()).limit(MAX_CANDIDATES).all()
    if not rows:
        return ReferenceCaseEvidence(
            status="insufficient_comparability", data_release=release,
            algorithm_version="reference_similarity.v1", configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(
                total_windows=total, eligible_windows=eligible_total,
                comparable_windows=0, returned_windows=0,
                exclusion_counts=exclusion_counts,
            ),
        )
    current = ReferenceCaseFeatureProfile(
        baseline_stage=str(snapshot.get("baseline_stage") or "unknown"), prediction_task=prediction_task,
        age=snapshot.get("age"), sex=snapshot.get("sex"),
        as_of=str(visits[-1]["visit_date"]), visit_count=len(visits),
        observation_span_days=int(summary.get("observation_span_days") or 0),
        feature_summary=summary,
        measurement_context_summary=summarize_measurement_context(visits),
    )
    empty_score = ReferenceCaseScoreBreakdown(
        conditional_similarity=0, coverage=0, ranking_score=0, available_weight=0,
    )
    candidates: list[ReferenceCaseProfile] = []
    for row in rows:
        feature_summary = row.feature_summary if isinstance(row.feature_summary, dict) else {}
        candidates.append(ReferenceCaseProfile(
            anonymous_case_code=row.anonymous_case_code,
            features=ReferenceCaseFeatureProfile(
                baseline_stage=row.baseline_stage or "unknown", prediction_task=row.prediction_task,
                age=row.age, sex=row.sex, as_of=row.as_of, visit_count=row.visit_count,
                observation_span_days=row.span_days, feature_summary=feature_summary,
                measurement_context_summary=row.measurement_context_summary or {},
            ),
            score=empty_score,
            outcome_status=row.outcome_status if row.outcome_status in {"positive", "negative", "unknown"} else "unknown",
            outcome_value=row.outcome_value or {}, outcome_source=row.outcome_source,
            outcome_reliability=row.outcome_reliability,
            source_trace=row.source_trace or {},
        ))
    scored = score_reference_candidates(current, candidates)
    selected = scored[:5]
    status = "available" if selected else "insufficient_comparability"
    return ReferenceCaseEvidence(
        status=status, data_release=release, algorithm_version="reference_similarity.v1",
        configuration_hash=token.similarity_config_hash,
        pool_statistics=ReferencePoolStatistics(
            total_windows=total, eligible_windows=eligible_total,
            comparable_windows=len(scored), returned_windows=len(selected),
            exclusion_counts=exclusion_counts,
        ),
        cases=selected,
    )


def query_reference_windows(
    db: Any,
    snapshot: Mapping[str, Any],
    token: EvidenceVersionToken,
    standard: Any | None = None,
) -> ReferenceCaseEvidence:
    """Query reference windows with an independent bounded transaction."""
    should_close_transaction = callable(getattr(db, "rollback", None))
    try:
        execute = getattr(db, "execute", None)
        if callable(execute):
            from sqlalchemy import text
            from app.core.config import settings

            execute(text(
                f"SET LOCAL statement_timeout = {max(1, int(settings.REFERENCE_CASE_QUERY_TIMEOUT_MS))}"
            ))
        return _query_reference_windows_in_transaction(db, snapshot, token, standard)
    finally:
        if should_close_transaction:
            db.rollback()


def build_evidence_bundle_once(db: Any, snapshot: Mapping[str, Any], token: EvidenceVersionToken) -> EvidenceBuildResult:
    try:
        standard = build_standard_evidence(db, token.standard, snapshot)
    except StandardEvidenceError as exc:
        raise EvidenceBuildError(exc.code) from exc
    try:
        references = query_reference_windows(db, snapshot, token, standard)
        status: Literal["complete", "partial"] = (
            "partial"
            if references.status in {"reference_query_failed", "reference_index_stale"}
            else "complete"
        )
    except Exception:
        references = ReferenceCaseEvidence(
            status="reference_query_failed",
            data_release=ReferenceDataRelease(logical_dataset=token.logical_dataset or str(snapshot.get("disease_code", "")), dataset_release_id=token.dataset_release_id, data_content_sha256=token.data_content_sha256),
            algorithm_version="reference_similarity.v1", configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(total_windows=0, eligible_windows=0, comparable_windows=0, returned_windows=0),
        )
        status = "partial"
    raw_batch_id = snapshot.get("generation_batch_id")
    try:
        generation_batch_id = UUID(str(raw_batch_id))
    except (TypeError, ValueError):
        generation_batch_id = uuid4()
    bundle = finalize_evidence_bundle(EvidenceBundle(
        evidence_bundle_id=uuid4(), generation_batch_id=generation_batch_id, disease_code=str(snapshot.get("disease_code", "fatty_liver")),
        created_at=datetime.now(timezone.utc), standard=standard, reference_cases=references,
    ))
    return EvidenceBuildResult(bundle=bundle, evidence_status=status, sources_projection=tuple(build_sources_projection(bundle)))


def build_evidence_bundle_with_retry(db: Any, snapshot: Mapping[str, Any], initial_token: EvidenceVersionToken) -> EvidenceBuildResult:
    token = initial_token
    for attempt in range(2):
        result = build_evidence_bundle_once(db, snapshot, token)
        current = read_version_token(db, str(snapshot.get("disease_code", "")), snapshot.get("disease_id"))
        if current == token:
            return result
        if attempt == 0:
            token = current
            continue
        raise EvidenceBuildError("evidence_version_changed")
    raise AssertionError("bounded retry exhausted")


def project_standard_rule(rule: Any, standard: Any) -> dict[str, Any]:
    projection = {
        "source_type": (
            "reference_range" if getattr(rule, "status", None) == "calculable"
            else "standard_evidence"
        ),
        "standard_version_id": standard.version.version_id,
    }
    projection.update({
        key: getattr(rule, key)
        for key in (
            "rule_id", "indicator", "unit", "lower", "upper", "status",
            "applicability_hash",
        )
        if hasattr(rule, key)
    })
    projection["standard_rule_id"] = projection.pop("rule_id", None)
    return projection


def project_reference_case(case: Any) -> dict[str, Any]:
    return {
        "source_type": "similar_case",
        "anonymous_case_code": case.anonymous_case_code,
        "score": case.score.model_dump(mode="json"),
        "overlap_features": [
            item.indicator for item in case.comparisons
            if item.status == "comparable"
        ],
        "outcome_status": case.outcome_status,
        "status": "available",
    }


def build_sources_projection(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    result = [project_standard_rule(rule, bundle.standard) for rule in bundle.standard.rules]
    result.extend(project_reference_case(case) for case in bundle.reference_cases.cases)
    assert all("patient_label" not in item for item in result)
    return result


__all__ = [
    "canonicalize_evidence_bundle",
    "finalize_evidence_bundle",
    "verify_evidence_bundle",
    "EvidenceVersionToken", "EvidenceBuildError", "EvidenceBuildResult", "preflight_evidence_versions",
    "read_version_token", "query_reference_windows", "build_evidence_bundle_once", "build_evidence_bundle_with_retry",
    "build_sources_projection",
]
