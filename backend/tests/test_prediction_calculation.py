from copy import deepcopy

import pytest

from app.schemas.synthetic_prediction_cases import GenerationConfig
from app.services.synthetic_prediction_cases import build_prediction_inputs, build_followup_outcomes, generate_cohort
from app.services.synthetic_prediction_fixtures import build_fixed_fixtures


def module():
    from app.services import prediction_calculation
    return prediction_calculation


def fixed(scenario, variant="base", disease="ad"):
    return next(f for f in build_fixed_fixtures()[0]
                if (f["scenario_id"], f["variant"], f["disease"]) == (scenario, variant, disease))


def fixture_inputs(fixture):
    return build_prediction_inputs(fixture["patients"], fixture["observations"])


def test_literal_history_projection_uses_nominal_calendar_days():
    m = module()
    rows = m.project_calculation_inputs(fixture_inputs(fixed("S01")))
    first = next(r for r in rows if r["horizon_months"] == 6)
    assert first["horizon_days"] == 182
    assert first["trend_interval_days"] == 184
    assert first["trend_prior_value"] == 24
    predictions = m.predict_baselines(rows)
    assert next(p["value"] for p in predictions if p["sample_id"] == first["sample_id"] and p["model_id"] == "history_trend") == pytest.approx(22 - 2 * 182 / 184)
    assert next(p["value"] for p in predictions if p["model_id"] == "last_value") == 22
    assert not {"actual", "actual_date", "pool", "mechanism", "baseline_stage"} & first.keys()


def test_s12_future_change_and_missing_label_cannot_change_predictions():
    m = module()
    before = m.project_calculation_inputs(fixture_inputs(fixed("S12")))
    after = m.project_calculation_inputs(fixture_inputs(fixed("S12", "future_changed")))
    assert before == after
    assert m.predict_baselines(before) == m.predict_baselines(after)


def test_zero_unknown_and_unavailable_histories_have_distinct_features():
    m = module()
    zero = m.project_calculation_inputs(fixture_inputs(fixed("S02")))[0]
    unknown = m.project_calculation_inputs(fixture_inputs(fixed("S03")))[0]
    late = m.project_calculation_inputs(fixture_inputs(fixed("S11", "late_known")))[0]
    assert (zero["n_pre"], zero["span_pre_days"]) == (0, 0)
    assert unknown["n_pre"] is late["n_pre"] is None
    assert {p["model_id"]: p["status"] for p in m.predict_baselines([zero])} == {
        "last_value": "valid", "history_trend": "abstain"}


def test_finite_out_of_range_trend_is_not_clipped():
    m = module()
    fixture = fixed("S04")
    for r in fixture["observations"]:
        if r["role"] == "history":
            r["value"], r["measured_on"], r["known_on"] = 29, "2024-01-30", "2024-01-30"
        elif r["role"] == "anchor":
            r["value"] = 30
    predictions = m.predict_baselines(m.project_calculation_inputs(fixture_inputs(fixture)))
    assert next(p for p in predictions if p["model_id"] == "history_trend" and p["sample_id"].endswith(":6m"))["value"] == 212


def test_default_samples_close_denominators_and_preserve_missing():
    m = module()
    data = generate_cohort(GenerationConfig())
    samples = m.build_engineering_samples(data["patients"], data["prediction_inputs"], data["followup_outcomes"], data["generation_audit"])
    assert len(samples) == 480
    assert sum(s["label_status"] == "valid" for s in samples) == 334
    assert sum(s["label_status"] == "absent" for s in samples) == 25
    assert sum(s["label_status"] == "pending" for s in samples) == 121
    predictions = m.predict_baselines(m.project_calculation_inputs(data["prediction_inputs"]))
    assert len(predictions) == 960
    assert sum(p["model_id"] == "last_value" and p["status"] == "valid" for p in predictions) == 480


def test_broken_and_cross_pool_links_are_rejected():
    m = module()
    data = generate_cohort(GenerationConfig(patients_per_disease=3, challenge_per_disease=1))
    args = [data[k] for k in ("patients", "prediction_inputs", "followup_outcomes", "generation_audit")]
    with pytest.raises(ValueError):
        m.build_engineering_samples(args[0], args[1], args[2][:-1], args[3])
    changed = deepcopy(args)
    changed[2][0]["subject_id"] = "another-subject"
    with pytest.raises(ValueError):
        m.build_engineering_samples(*changed)
    changed = deepcopy(args)
    changed[3][0]["dependency_group_id"] = "wrong"
    with pytest.raises(ValueError):
        m.build_engineering_samples(*changed)


def test_unknown_and_excluded_population_remain_distinct():
    m = module()
    for variant, state in [("diagnosis_unknown", "pending"), ("diagnosis_excluded", "ineligible")]:
        fixture = fixed("S20", variant)
        p = fixture["patients"][0]
        audit = [{"subject_id": p["subject_id"], "dependency_group_id": p["dependency_group_id"], "pool": "challenge_pool"}]
        samples = m.build_engineering_samples(fixture["patients"], fixture_inputs(fixture),
                    build_followup_outcomes(fixture["patients"], fixture["observations"]), audit)
        assert {s["anchor_status"] for s in samples} == {state}
        assert {s["label_status"] for s in samples} == {"not_applicable"}


def test_evaluation_denominators_and_pairing_are_closed():
    m = module()
    data = generate_cohort(GenerationConfig())
    samples = m.build_engineering_samples(data["patients"], data["prediction_inputs"], data["followup_outcomes"], data["generation_audit"])
    predictions = m.predict_baselines(m.project_calculation_inputs(data["prediction_inputs"]))
    result = m.evaluate_baselines(samples, predictions)
    assert len(result["evaluation"]["comparisons"]) == 16
    assert len(result["bootstrap_plans"]) == 8
    for comparison in result["evaluation"]["comparisons"]:
        n = comparison["counts"]
        assert n["N_patient"] == n["N_anchor_eligible"] + n["N_anchor_ineligible"] + n["N_anchor_pending"]
        assert n["N_branch_eligible"] == n["N_label_valid"] + n["N_label_absent"] + n["N_label_pending"]
        assert n["N_label_valid"] == n["N_pred_valid"] + n["N_pred_abstain"] + n["N_pred_error"]
        assert n["N_label_valid"] == sum(comparison["joint_states"].values())
        assert comparison["performance"]["status"] == "not_assessable"
        if comparison["pool"] == "challenge_pool":
            assert len(result["bootstrap_plans"][comparison["comparison_id"]]["draw_indices"]) == 2000
        else:
            assert not comparison["intervals"]


def test_missing_and_nonfinite_predictions_remain_failures_in_denominator():
    m = module()
    data = generate_cohort(GenerationConfig(patients_per_disease=6, challenge_per_disease=2))
    samples = m.build_engineering_samples(data["patients"], data["prediction_inputs"], data["followup_outcomes"], data["generation_audit"])
    predictions = m.predict_baselines(m.project_calculation_inputs(data["prediction_inputs"]))
    sample = next(s for s in samples if s["pool"] == "development_pool" and s["label_status"] == "valid")
    predictions = [p for p in predictions if (p["sample_id"], p["model_id"]) != (sample["sample_id"], "last_value")]
    result = m.evaluate_baselines(samples, predictions)
    main = next(c for c in result["evaluation"]["comparisons"] if c["comparison_id"] == f'{sample["task_id"]}:development_pool:main')
    assert main["counts"]["N_pred_error"] == 1
    assert main["complete_output"] is False
    assert main["performance"]["known_failures"]
    assert main["counts"]["N_label_valid"] == main["counts"]["N_pair_valid"] + 1


def test_history_comparison_does_not_hide_a_missing_baseline_output():
    m = module()
    data = generate_cohort(GenerationConfig(patients_per_disease=6, challenge_per_disease=2))
    samples = m.build_engineering_samples(data["patients"], data["prediction_inputs"], data["followup_outcomes"], data["generation_audit"])
    predictions = m.predict_baselines(m.project_calculation_inputs(data["prediction_inputs"]))
    sample = next(s for s in samples if s["label_status"] == "valid" and s["trend_prior_value"] is not None)
    predictions = [p for p in predictions if (p["sample_id"], p["model_id"]) != (sample["sample_id"], "last_value")]
    result = m.evaluate_baselines(samples, predictions)
    c = next(c for c in result["evaluation"]["comparisons"] if c["comparison_id"] == f'{sample["task_id"]}:{sample["pool"]}:history')
    assert c["joint_states"]["baseline_unavailable"] == 1
    assert c["complete_output"] is False
