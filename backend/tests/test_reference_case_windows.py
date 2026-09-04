import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_evidence import ReferenceDataRelease
from app.services.reference_case_windows import (
    ReferenceCaseWindowWrite,
    _group_active_source_rows,
    _release_from_metadata,
    build_window_profiles,
    resolve_reference_dataset,
)


def test_reference_window_write_rejects_noncanonical_sex():
    payload = {
        "disease_code": "fatty_liver",
        "logical_dataset": "longitudinal_300",
        "dataset_release_id": "release-1",
        "prediction_task": "fatty_liver.pre_cirrhosis_to_progression",
        "anonymous_case_code": "CASE-ABCD-2345",
        "as_of": "2025-06-01",
        "profile_schema_version": "reference_case_profile.v1",
        "age": 60,
        "sex": "unknown",
        "visit_count": 3,
        "span_days": 180,
        "outcome_status": "unknown",
        "outcome_source": "not_observed",
        "outcome_reliability": "low",
        "is_synthetic": False,
        "eligibility_config_hash": "a" * 64,
        "data_content_sha256": "b" * 64,
        "source_trace": {},
        "feature_summary": {},
        "measurement_context_summary": {},
        "timeline_sha256": "c" * 64,
        "timeline_canonical_json": "{}",
    }

    with pytest.raises(ValidationError):
        ReferenceCaseWindowWrite.model_validate(payload)


def _release():
    return ReferenceDataRelease(logical_dataset="longitudinal_300", dataset_release_id="fatty-2026", data_content_sha256="a" * 64)


def _rows(outcome_value="explicit_cirrhosis"):
    visits = [
        {"visit_date": "2025-01-01", "indicators": [{"name": "alt", "value": 20, "unit": "U/L"}], "visit_context": {"assay_platform": "A"}},
        {"visit_date": "2025-03-01", "indicators": [{"name": "alt", "value": 21, "unit": "U/L"}], "visit_context": {"assay_platform": "A"}},
        {"visit_date": "2025-06-01", "indicators": [{"name": "alt", "value": 22, "unit": "U/L"}], "visit_context": {"assay_platform": "B"}},
        {"visit_date": "2026-01-01", "indicators": [{"name": "alt", "value": 23, "unit": "U/L"}], "visit_context": {"assay_platform": "C"}},
    ]
    return [{
        "disease_code": "fatty_liver", "dataset_release_id": "fatty-2026", "is_synthetic": False,
        "anonymous_case_code": "CASE-ABCD-2345", "source_trace": {"source": "registry"},
        "outcome_source": outcome_value, "outcome_reliability": "high", "task_compatible": True,
        "outcome_status": "positive",
        "outcome_value": {"event_date": "2026-05-31", "event_type": "cirrhosis"},
        "timeline_valid": True,
        "baseline_stage": "pre_cirrhosis",
        "prediction_task": "fatty_liver.pre_cirrhosis_to_progression",
        "visits": visits,
    }]


def test_build_profiles_start_at_third_visit_and_hash_prefix_only():
    result = build_window_profiles(_rows(), "fatty_liver", _release())
    assert result.eligible_windows == 2
    assert len(result.profiles) == 2
    assert result.profiles[0].as_of == "2025-06-01"
    assert result.profiles[0].feature_summary["indicators"]["alt"]["last"] == 22
    assert result.profiles[0].prediction_task == "fatty_liver.pre_cirrhosis_to_progression"
    assert result.profiles[0].outcome_reliability == "high"
    assert result.profiles[0].is_synthetic is False
    assert result.profiles[0].profile_schema_version.endswith("+aaaaaaaaaaaa")
    assert result.profiles[0].timeline_sha256 == hashlib.sha256(
        result.profiles[0].timeline_canonical_json.encode("utf-8")
    ).hexdigest()


def test_future_outcome_does_not_change_prefix_features():
    first = build_window_profiles(_rows("explicit_cirrhosis"), "fatty_liver", _release()).profiles[0]
    second = build_window_profiles(_rows("explicit_hcc"), "fatty_liver", _release()).profiles[0]
    assert first.feature_summary == second.feature_summary
    assert first.timeline_sha256 == second.timeline_sha256
    assert first.measurement_context_summary == second.measurement_context_summary


def test_profile_drops_free_text_and_unapproved_trace_fields():
    rows = _rows()
    rows[0]["source_trace"] = {
        "source": "registry",
        "patient_name": "不得保存",
        "absolute_path": r"C:\\private\\patient.csv",
    }
    rows[0]["outcome_value"] = {
        "event_type": "cirrhosis",
        "event_date": "2026-05-31",
        "clinical_note": "不得保存",
    }

    profile = build_window_profiles(rows, "fatty_liver", _release()).profiles[0]

    assert profile.source_trace == {"source": "registry"}
    assert profile.outcome_value == {
        "event_type": "cirrhosis", "event_date": "2026-05-31",
    }
    assert "不得保存" not in profile.model_dump_json()


def test_release_identity_requires_one_active_id_and_hash():
    release = _release_from_metadata([
        {
            "logical_dataset": "fatty_liver",
            "dataset_release_id": "fatty-2026",
            "dataset_active": True,
            "data_content_sha256": "a" * 64,
        }
    ], "fatty_liver")

    assert release.dataset_release_id == "fatty-2026"
    assert release.data_content_sha256 == "a" * 64


def test_cli_disease_selector_maps_to_importer_logical_dataset():
    assert resolve_reference_dataset("fatty_liver") == ("fatty_liver", "longitudinal_300")
    assert resolve_reference_dataset("ad") == ("ad", "ad_longitudinal_300")
    assert resolve_reference_dataset("longitudinal_300") == ("fatty_liver", "longitudinal_300")


def test_imported_case_record_contract_is_grouped_without_new_metadata_fields():
    metadata = {
        "logical_dataset": "longitudinal_300", "dataset_release_id": "fatty-2026",
        "dataset_active": True, "data_content_sha256": "a" * 64,
        "visit_date": "2025-01-01", "visit_index": 1, "patient_age": 62,
        "sex": "female", "final_stage": "cirrhosis",
        "event_dates": {"cirrhosis_date": "2025-08-01"}, "is_synthetic": False,
        "source_document": "private-source.docx",
    }
    rows = [SimpleNamespace(
        id=10, anonymous_case_code="CASE-ABCD-2345", case_metadata=metadata,
        indicators=[{"name": "alt", "value": 20, "unit": "U/L"}],
    )]

    grouped = _group_active_source_rows(rows, "fatty_liver", "longitudinal_300", _release())

    assert grouped[0]["age"] == 62
    assert grouped[0]["event_dates"] == {"cirrhosis_date": "2025-08-01"}
    assert grouped[0]["source_trace"] == {
        "source_system": "source_document", "registry_id": "fatty-2026", "record_id": 10,
    }
    assert grouped[0]["visits"][0]["visit_date"] == "2025-01-01"


def test_window_outcome_is_limited_to_365_days_after_as_of():
    rows = _rows()
    rows[0].pop("outcome_source")
    rows[0]["event_dates"] = {"cirrhosis_date": "2025-08-01"}
    rows[0]["visits"] = [
        {"visit_date": visit_date, "indicators": [{"name": "alt", "value": value, "unit": "U/L"}]}
        for visit_date, value in [
            ("2024-01-01", 20), ("2024-05-01", 21), ("2024-09-01", 22), ("2025-01-01", 23),
        ]
    ]

    first = build_window_profiles(rows, "fatty_liver", _release()).profiles[0]

    assert first.as_of == "2024-09-01"
    assert first.outcome_status == "positive"
    assert first.outcome_source == "explicit_cirrhosis"
    assert first.outcome_value["event_date"] == "2025-08-01"


def test_windows_without_horizon_outcome_and_synthetic_windows_are_retained_as_excluded():
    rows = _rows()
    rows[0].pop("outcome_source")
    rows[0]["event_dates"] = {"cirrhosis_date": "2028-08-01"}
    rows[0]["is_synthetic"] = True

    result = build_window_profiles(rows, "fatty_liver", _release())

    assert len(result.profiles) == result.total_windows == 2
    assert result.eligible_windows == 0
    assert all(profile.eligibility_status == "excluded" for profile in result.profiles)
    assert all(profile.outcome_status == "unknown" for profile in result.profiles)


def test_precomputed_outcome_outside_horizon_is_not_copied_into_window():
    rows = _rows()
    rows[0]["outcome_value"] = {"event_date": "2030-01-01", "event_type": "cirrhosis"}

    profile = build_window_profiles(rows, "fatty_liver", _release()).profiles[0]

    assert profile.outcome_status == "unknown"
    assert profile.outcome_reliability == "low"
    assert profile.eligibility_status == "excluded"
