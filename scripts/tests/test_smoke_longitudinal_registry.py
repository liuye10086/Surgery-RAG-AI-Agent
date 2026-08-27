import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "generated"


def test_real_csv_smoke_fixture_has_online_shape_without_identity():
    from scripts.smoke_longitudinal_registry import load_online_smoke_case

    case, visits = load_online_smoke_case(
        "fatty_liver",
        DATA / "longitudinal_300" / "patients.csv",
        DATA / "longitudinal_300" / "visits.csv",
        "pre_cirrhosis",
    )
    assert case["baseline_stage"] == "pre_cirrhosis"
    assert case["sex"] in {"male", "female", None}
    assert "age" not in case
    assert "patient_id" not in case
    assert len(visits) >= 3
    assert all("patient_id" not in visit for visit in visits)
    assert all(visit["indicators"] for visit in visits)


def test_real_csv_smoke_fixture_covers_cirrhosis_and_ad_mci():
    from scripts.smoke_longitudinal_registry import load_online_smoke_case

    cirrhosis, liver_visits = load_online_smoke_case(
        "fatty_liver",
        DATA / "longitudinal_300" / "patients.csv",
        DATA / "longitudinal_300" / "visits.csv",
        "cirrhosis",
    )
    ad, ad_visits = load_online_smoke_case(
        "ad",
        DATA / "ad_longitudinal_300" / "patients.csv",
        DATA / "ad_longitudinal_300" / "visits.csv",
        "mci",
    )
    assert cirrhosis["baseline_stage"] == "cirrhosis"
    assert ad["baseline_stage"] == "mci"
    assert len(liver_visits) >= 3
    assert len(ad_visits) >= 3


def test_smoke_payload_sanitizer_rejects_patient_identifiers():
    from scripts.smoke_longitudinal_registry import assert_safe_payload

    assert_safe_payload({"task": "ad.pre_dementia_to_dementia"})
    try:
        assert_safe_payload({"patient_id": "P001"})
    except ValueError as error:
        assert str(error) == "sensitive_output_detected"
    else:
        raise AssertionError("patient identifier was accepted")


def test_complete_suite_summary_includes_release_outcome_stage_and_trends():
    from backend.tests.test_longitudinal_prediction_contract import (
        _ad_visits,
        _complete_ad_suite,
    )
    from app.services.disease_progression import AD_ADAPTER
    from app.services.longitudinal_prediction import run_longitudinal_prediction
    from scripts.smoke_longitudinal_registry import _result_summary

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        _complete_ad_suite(),
    )
    summary = _result_summary(result)

    assert summary["release_set_id"] == "ad-set-v1"
    assert summary["outcome"]["status"] == "available"
    assert summary["stage"]["status"] == "available"
    assert summary["trends"]["available_count"] == 2
    assert summary["trends"]["required_count"] == 2
