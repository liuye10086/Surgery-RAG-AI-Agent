"""Real PostgreSQL acceptance for querying and persisting report evidence."""

from datetime import datetime, timezone
from uuid import uuid4

from app.db.models import AIReport, CaseRecord
from app.schemas.longitudinal_evidence import (
    EvidenceBundle,
    EvidenceDocument,
    EvidenceVersion,
    StandardEvidence,
)
from app.services.evidence_bundle import (
    EvidenceVersionToken,
    finalize_evidence_bundle,
    query_reference_windows,
    verify_evidence_bundle,
)
from app.services.reference_case_eligibility import ELIGIBILITY_CONFIG_HASH
from app.services.reference_case_similarity import SIMILARITY_CONFIG_HASH
from app.services.standard_evidence import StandardVersionToken
from app.services.reference_case_windows import synchronize_reference_case_windows


def _seed_active_release(db):
    for index, (visit_date, value) in enumerate([
        ("2024-01-01", 20.0), ("2024-04-01", 22.0),
        ("2024-07-01", 24.0), ("2024-10-01", 26.0),
    ], start=1):
        db.add(CaseRecord(
            disease_id=1, patient_label="source-patient-001",
            anonymous_case_code="CASE-ABCD-2345",
            indicators=[{"name": "alt", "value": value, "unit": "U/L"}],
            confirmed=True,
            case_metadata={
                "logical_dataset": "longitudinal_300", "source_dataset": "longitudinal_300",
                "dataset_release_id": "fl-integration-v1", "dataset_active": True,
                "data_content_sha256": "a" * 64, "visit_date": visit_date,
                "visit_index": index, "patient_age": 62, "sex": "female",
                "final_stage": "cirrhosis", "event_dates": {"cirrhosis_date": "2024-12-15"},
                "source_document": "source-001.docx", "is_synthetic": False,
            },
        ))
    db.commit()


def _snapshot():
    return {
        "disease_id": 1,
        "disease_code": "fatty_liver",
        "baseline_stage": "pre_cirrhosis",
        "age": 62,
        "sex": "female",
        "visits": [
            {
                "visit_date": visit_date,
                "indicators": [{"name": "alt", "value": value, "unit": "U/L"}],
                "visit_context": {},
            }
            for visit_date, value in [
                ("2024-01-01", 20.0), ("2024-04-01", 22.0),
                ("2024-07-01", 24.0), ("2024-10-01", 26.0),
            ]
        ],
    }


def test_query_and_report_snapshot_round_trip_on_postgres(db):
    _seed_active_release(db)
    synchronize_reference_case_windows(db, "fatty_liver", apply=True)
    token = EvidenceVersionToken(
        standard=StandardVersionToken(1, 1, 1, "b" * 64, "b" * 64),
        dataset_release_id="fl-integration-v1",
        data_content_sha256="a" * 64,
        eligibility_config_hash=ELIGIBILITY_CONFIG_HASH,
        similarity_config_hash=SIMILARITY_CONFIG_HASH,
        logical_dataset="longitudinal_300",
    )

    references = query_reference_windows(db, _snapshot(), token)

    assert references.status == "available"
    assert references.pool_statistics.total_windows == 2
    assert references.pool_statistics.eligible_windows == 2
    assert references.pool_statistics.returned_windows >= 1
    assert references.cases[0].anonymous_case_code == "CASE-ABCD-2345"
    assert "source-patient-001" not in references.model_dump_json()

    standard = StandardEvidence(
        status="available",
        document=EvidenceDocument(
            document_id=1, title="integration standard", filename="standard.docx",
            content_sha256="b" * 64,
        ),
        version=EvidenceVersion(
            version_id=1, version_label="v1", content_sha256="b" * 64,
            parser_version="integration",
        ),
    )
    bundle = finalize_evidence_bundle(EvidenceBundle(
        evidence_bundle_id=uuid4(), generation_batch_id=uuid4(),
        disease_code="fatty_liver", created_at=datetime.now(timezone.utc),
        standard=standard, reference_cases=references,
    ))
    report = AIReport(
        user_id=1, query="CASE-TEST-2345", content="saved content", status="completed",
        analysis_type="longitudinal_predictive", disease_id=1,
        prediction_result={}, input_snapshot=_snapshot(),
        evidence_snapshot=bundle.model_dump(mode="json"),
        evidence_snapshot_sha256=bundle.integrity.evidence_snapshot_sha256,
        evidence_status="complete", standard_evidence_status="available",
        reference_case_status="available",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    loaded = EvidenceBundle.model_validate(report.evidence_snapshot)
    assert report.evidence_snapshot_sha256 == loaded.integrity.evidence_snapshot_sha256
    assert verify_evidence_bundle(loaded) is True
