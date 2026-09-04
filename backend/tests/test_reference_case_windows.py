import hashlib

from app.schemas.longitudinal_evidence import ReferenceDataRelease
from app.services.reference_case_windows import build_window_profiles


def _release():
    return ReferenceDataRelease(logical_dataset="fatty_liver", dataset_release_id="fatty-2026", data_content_sha256="a" * 64)


def _rows(outcome_value="explicit_cirrhosis"):
    visits = [
        {"visit_date": "2025-01-01", "indicators": [{"name": "alt", "value": 20}], "visit_context": {"assay_platform": "A"}},
        {"visit_date": "2025-03-01", "indicators": [{"name": "alt", "value": 21}], "visit_context": {"assay_platform": "A"}},
        {"visit_date": "2025-06-01", "indicators": [{"name": "alt", "value": 22}], "visit_context": {"assay_platform": "B"}},
        {"visit_date": "2026-01-01", "indicators": [{"name": "alt", "value": 23}], "visit_context": {"assay_platform": "C"}},
    ]
    return [{
        "disease_code": "fatty_liver", "dataset_release_id": "fatty-2026", "is_synthetic": False,
        "anonymous_case_code": "CASE-ABCD-2345", "source_trace": {"source": "registry"},
        "outcome_source": outcome_value, "outcome_reliability": "high", "task_compatible": True,
        "timeline_valid": True, "visits": visits,
    }]


def test_build_profiles_start_at_third_visit_and_hash_prefix_only():
    result = build_window_profiles(_rows(), "fatty_liver", _release())
    assert result.eligible_windows == 2
    assert len(result.profiles) == 2
    assert result.profiles[0].as_of == "2025-06-01"
    assert result.profiles[0].feature_summary["indicators"]["alt"]["last"] == 22
    assert result.profiles[0].timeline_sha256 == hashlib.sha256(
        result.profiles[0].timeline_canonical_json.encode("utf-8")
    ).hexdigest()


def test_future_outcome_does_not_change_prefix_features():
    first = build_window_profiles(_rows("explicit_cirrhosis"), "fatty_liver", _release()).profiles[0]
    second = build_window_profiles(_rows("explicit_hcc"), "fatty_liver", _release()).profiles[0]
    assert first.feature_summary == second.feature_summary
    assert first.timeline_sha256 == second.timeline_sha256
    assert first.measurement_context_summary == second.measurement_context_summary

