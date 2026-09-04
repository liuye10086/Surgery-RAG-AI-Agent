from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.schemas.longitudinal_evidence import (
    EvidenceBundle,
    EvidenceDocument,
    EvidenceVersion,
    ReferenceCaseEvidence,
    ReferenceDataRelease,
    ReferencePoolStatistics,
    StandardEvidence,
)
from app.services.evidence_bundle import (
    EvidenceBuildError,
    EvidenceBuildResult,
    EvidenceVersionToken,
    build_evidence_bundle_with_retry,
    build_sources_projection,
)
from app.services.standard_evidence import StandardVersionToken


def _standard():
    return StandardEvidence(
        status="available",
        document=EvidenceDocument(document_id=1, title="std", filename="std.pdf", content_sha256="a" * 64),
        version=EvidenceVersion(version_id=2, version_label="v1", content_sha256="b" * 64, parser_version="p1"),
    )


def _bundle(status="no_eligible_cases"):
    return EvidenceBundle(
        evidence_bundle_id=uuid4(), generation_batch_id=uuid4(), disease_code="fatty_liver",
        created_at=datetime.now(timezone.utc), standard=_standard(),
        reference_cases=ReferenceCaseEvidence(
            status=status, data_release=ReferenceDataRelease(logical_dataset="fatty_liver", dataset_release_id="r1", data_content_sha256="c" * 64),
            algorithm_version="reference_similarity.v1", configuration_hash="d" * 64,
            pool_statistics=ReferencePoolStatistics(total_windows=0, eligible_windows=0, comparable_windows=0, returned_windows=0),
        ),
    )


def test_standard_change_retries_once_then_fails():
    token = EvidenceVersionToken(StandardVersionToken(1, 2, 3, "a" * 64, "b" * 64), "r", "c" * 64, "d" * 64, "e" * 64)
    result = EvidenceBuildResult(bundle=_bundle(), evidence_status="complete", sources_projection=())
    with patch("app.services.evidence_bundle.build_evidence_bundle_once", return_value=result), patch("app.services.evidence_bundle.read_version_token", side_effect=[token, token.__class__(token.standard, "r2", "c" * 64, "d" * 64, "e" * 64), token.__class__(token.standard, "r3", "c" * 64, "d" * 64, "e" * 64)]):
        with pytest.raises(EvidenceBuildError) as error:
            build_evidence_bundle_with_retry(SimpleNamespace(), {"disease_code": "fatty_liver"}, token)
    assert error.value.code == "evidence_version_changed"


def test_reference_query_failure_keeps_standard_and_marks_partial():
    token = EvidenceVersionToken(StandardVersionToken(1, 2, 3, "a" * 64, "b" * 64), "r", "c" * 64, "d" * 64, "e" * 64)
    result = EvidenceBuildResult(bundle=_bundle("reference_query_failed"), evidence_status="partial", sources_projection=())
    with patch("app.services.evidence_bundle.build_evidence_bundle_once", return_value=result), patch("app.services.evidence_bundle.read_version_token", return_value=token):
        built = build_evidence_bundle_with_retry(SimpleNamespace(), {"disease_code": "fatty_liver"}, token)
    assert built.evidence_status == "partial"
    assert built.bundle.reference_cases.status == "reference_query_failed"
    assert built.bundle.standard.status == "available"

