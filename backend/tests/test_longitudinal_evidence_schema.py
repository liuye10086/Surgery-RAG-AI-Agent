from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_evidence import EvidenceBundle
from app.services.evidence_bundle import (
    finalize_evidence_bundle,
    verify_evidence_bundle,
)


@pytest.fixture
def bundle_payload():
    return {
        "schema_version": "longitudinal_evidence_bundle.v1",
        "evidence_bundle_id": "11111111-1111-4111-8111-111111111111",
        "generation_batch_id": "22222222-2222-4222-8222-222222222222",
        "disease_code": "fatty_liver",
        "created_at": "2026-09-04T00:00:00Z",
        "standard": {
            "status": "available",
            "document": {
                "document_id": 1,
                "title": "脂肪肝标准",
                "filename": "fatty_liver_standard.docx",
                "content_sha256": "a" * 64,
                "issuer": None,
                "publication_date": None,
                "external_identifier": None,
                "source_url": None,
            },
            "version": {
                "version_id": 2,
                "version_label": "fatty-liver-v1",
                "content_sha256": "a" * 64,
                "parser_version": "standard-docx.v1",
                "approved_at": "2026-09-01T00:00:00Z",
                "effective_from": None,
            },
            "rules": [
                {
                    "rule_id": 3,
                    "indicator": "alt",
                    "display_name": "谷丙转氨酶",
                    "status": "calculable",
                    "machine_actionability": "calculable",
                    "unit": "U/L",
                    "lower": 7.0,
                    "upper": 40.0,
                    "lower_inclusive": True,
                    "upper_inclusive": True,
                    "latest_value": 45.0,
                    "numeric_interpretation": "above_range",
                    "interpretation": "ALT 参考范围",
                    "applicability": {},
                    "applicability_hash": "b" * 64,
                    "conditions": {
                        "status": "matched",
                        "satisfied": [],
                        "missing": [],
                        "mismatched": [],
                    },
                    "source": {
                        "segment_id": 4,
                        "section_title": "实验室检查",
                        "paragraph_index": None,
                        "table_index": 1,
                        "row_index": 2,
                        "column_index": 3,
                        "page_number": None,
                        "raw_text": "ALT 7-40 U/L",
                    },
                }
            ],
            "warnings": [],
        },
        "reference_cases": {
            "status": "available",
            "data_release": {
                "logical_dataset": "longitudinal_300",
                "dataset_release_id": "release-1",
                "data_content_sha256": "c" * 64,
            },
            "algorithm_version": "reference_similarity.v1",
            "configuration_hash": "d" * 64,
            "pool_statistics": {
                "total_windows": 10,
                "eligible_windows": 3,
                "comparable_windows": 1,
                "returned_windows": 1,
                "exclusion_counts": {"synthetic_source": 7},
            },
            "cases": [
                {
                    "anonymous_case_code": "CASE-ABCD-2345",
                    "features": {
                        "baseline_stage": "pre_cirrhosis",
                        "prediction_task": "fatty_liver.pre_cirrhosis_to_progression",
                        "age": 61,
                        "sex": "female",
                        "as_of": "2025-01-01",
                        "visit_count": 4,
                        "observation_span_days": 730,
                        "feature_summary": {"indicators": {"alt": {"last": 42.0}}},
                        "measurement_context_summary": {},
                    },
                    "score": {
                        "conditional_similarity": 72.1234567,
                        "coverage": 0.8,
                        "ranking_score": 57.6987654,
                        "available_weight": 80,
                        "dimensions": {"stage_task": 1.0},
                    },
                    "comparisons": [],
                    "outcome_status": "positive",
                    "outcome_value": {"event": "cirrhosis"},
                    "outcome_source": "explicit_cirrhosis",
                    "outcome_reliability": "high",
                    "source_trace": {"source_id": "source-a"},
                }
            ],
            "warnings": [],
        },
        "warnings": [],
        "integrity": {
            "canonicalization_version": "v1",
            "hash_algorithm": "sha256",
            "evidence_snapshot_sha256": None,
        },
    }


def test_bundle_forbids_unknown_fields_and_hashes_without_self_reference(bundle_payload):
    payload = deepcopy(bundle_payload)
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)

    bundle = finalize_evidence_bundle(EvidenceBundle.model_validate(bundle_payload))
    assert bundle.integrity.evidence_snapshot_sha256 is not None
    assert verify_evidence_bundle(bundle) is True
    changed = bundle.model_copy(update={"warnings": ["changed"]})
    assert verify_evidence_bundle(changed) is False


def test_reference_case_schema_has_no_identity_label(bundle_payload):
    payload = deepcopy(bundle_payload)
    payload["reference_cases"]["cases"][0]["patient_label"] = "forbidden"
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)


def test_scores_are_finite_bounded_and_quantized(bundle_payload):
    bundle = EvidenceBundle.model_validate(bundle_payload)
    score = bundle.reference_cases.cases[0].score
    assert score.conditional_similarity == 72.123457
    assert score.ranking_score == 57.698765

    invalid = deepcopy(bundle_payload)
    invalid["reference_cases"]["cases"][0]["score"]["coverage"] = float("nan")
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(invalid)


def test_timezone_is_required(bundle_payload):
    payload = deepcopy(bundle_payload)
    payload["created_at"] = "2026-09-04T00:00:00"
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)
