"""Canonicalization and integrity helpers for EvidenceBundle v1."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4

from app.schemas.longitudinal_evidence import (
    EvidenceBundle,
    ReferenceCaseEvidence,
    ReferenceDataRelease,
    ReferencePoolStatistics,
)
from app.services.reference_case_eligibility import ELIGIBILITY_CONFIG_HASH
from app.services.reference_case_similarity import WEIGHTS
from app.services.standard_evidence import StandardEvidenceError, StandardVersionToken, build_standard_evidence, preflight_standard


SIMILARITY_CONFIG_HASH = hashlib.sha256(json.dumps(dict(WEIGHTS), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class EvidenceVersionToken:
    standard: StandardVersionToken
    dataset_release_id: str
    data_content_sha256: str
    eligibility_config_hash: str
    similarity_config_hash: str


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
        from app.services.reference_case_windows import load_active_reference_rows

        release, _ = load_active_reference_rows(db, disease_code)
        return EvidenceVersionToken(standard, release.dataset_release_id, release.data_content_sha256, ELIGIBILITY_CONFIG_HASH, SIMILARITY_CONFIG_HASH)
    except StandardEvidenceError as exc:
        raise EvidenceBuildError(exc.code) from exc
    except Exception as exc:
        code = getattr(exc, "code", "reference_index_stale")
        raise EvidenceBuildError(code) from exc


def read_version_token(db: Any, disease_code: str) -> EvidenceVersionToken:
    return preflight_evidence_versions(db, int(0), disease_code)


def query_reference_windows(db: Any, snapshot: Mapping[str, Any], token: EvidenceVersionToken) -> ReferenceCaseEvidence:
    release = ReferenceDataRelease(logical_dataset=snapshot.get("disease_code", ""), dataset_release_id=token.dataset_release_id, data_content_sha256=token.data_content_sha256)
    return ReferenceCaseEvidence(
        status="no_eligible_cases", data_release=release, algorithm_version="reference_similarity.v1",
        configuration_hash=token.similarity_config_hash,
        pool_statistics=ReferencePoolStatistics(total_windows=0, eligible_windows=0, comparable_windows=0, returned_windows=0),
    )


def build_evidence_bundle_once(db: Any, snapshot: Mapping[str, Any], token: EvidenceVersionToken) -> EvidenceBuildResult:
    try:
        standard = build_standard_evidence(db, token.standard, snapshot)
    except StandardEvidenceError as exc:
        raise EvidenceBuildError(exc.code) from exc
    try:
        references = query_reference_windows(db, snapshot, token)
        status: Literal["complete", "partial"] = "complete"
    except Exception:
        references = ReferenceCaseEvidence(
            status="reference_query_failed",
            data_release=ReferenceDataRelease(logical_dataset=str(snapshot.get("disease_code", "")), dataset_release_id=token.dataset_release_id, data_content_sha256=token.data_content_sha256),
            algorithm_version="reference_similarity.v1", configuration_hash=token.similarity_config_hash,
            pool_statistics=ReferencePoolStatistics(total_windows=0, eligible_windows=0, comparable_windows=0, returned_windows=0),
        )
        status = "partial"
    bundle = EvidenceBundle(
        evidence_bundle_id=uuid4(), generation_batch_id=uuid4(), disease_code=str(snapshot.get("disease_code", "fatty_liver")),
        created_at=datetime.now(timezone.utc), standard=standard, reference_cases=references,
    )
    return EvidenceBuildResult(bundle=bundle, evidence_status=status, sources_projection=tuple(build_sources_projection(bundle)))


def build_evidence_bundle_with_retry(db: Any, snapshot: Mapping[str, Any], initial_token: EvidenceVersionToken) -> EvidenceBuildResult:
    token = initial_token
    # Capture the version observed immediately before the model/evidence work.
    # This makes a mid-flight release switch detectable without holding a
    # transaction or lock across the expensive build.
    observed = read_version_token(db, str(snapshot.get("disease_code", "")))
    if observed != token:
        token = observed
    for attempt in range(2):
        result = build_evidence_bundle_once(db, snapshot, token)
        current = read_version_token(db, str(snapshot.get("disease_code", "")))
        if current == token:
            return result
        if attempt == 0:
            token = current
            continue
        raise EvidenceBuildError("evidence_version_changed")
    raise AssertionError("bounded retry exhausted")


def project_standard_rule(rule: Any) -> dict[str, Any]:
    return {key: getattr(rule, key) for key in ("rule_id", "indicator", "unit", "lower", "upper", "status", "applicability_hash") if hasattr(rule, key)}


def project_reference_case(case: Any) -> dict[str, Any]:
    return {"anonymous_case_code": case.anonymous_case_code, "score": case.score.model_dump(mode="json"), "outcome_status": case.outcome_status}


def build_sources_projection(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    result = [project_standard_rule(rule) for rule in bundle.standard.rules]
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
