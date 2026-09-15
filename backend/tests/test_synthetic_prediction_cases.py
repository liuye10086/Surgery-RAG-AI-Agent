"""Behavioral contracts for the isolated synthetic engineering dataset."""

from copy import deepcopy
from datetime import date

import pytest


def core():
    from app.schemas.synthetic_prediction_cases import GenerationConfig
    from app.services import synthetic_prediction_cases

    return GenerationConfig, synthetic_prediction_cases


def test_calendar_months_respects_month_end_and_leap_year():
    _, module = core()
    assert module.add_calendar_months(date(2023, 8, 31), 6) == date(2024, 2, 29)
    assert module.add_calendar_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert module.add_calendar_months(date(2024, 1, 31), 6) == date(2024, 7, 31)


@pytest.mark.parametrize("kwargs", [{"seed": True}, {"patients_per_disease": 1},
                                     {"challenge_per_disease": 0}, {"seed": -1}])
def test_config_rejects_invalid_parameters(kwargs):
    Config, _ = core()
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_generation_is_reproducible_and_seed_changes_measurements():
    Config, module = core()
    config = Config(patients_per_disease=15, challenge_per_disease=5)
    first = module.generate_cohort(config)
    assert first == module.generate_cohort(config)
    second = module.generate_cohort(config.model_copy(update={"seed": 20260915}))
    assert [(r["measured_on"], r["value"]) for r in first["observations"]] != [
        (r["measured_on"], r["value"]) for r in second["observations"]]


def test_identical_source_copies_do_not_change_inputs_or_outcomes():
    Config, module = core()
    result = module.generate_cohort(Config(patients_per_disease=15, challenge_per_disease=5))
    doubled = result["observations"] + deepcopy(result["observations"])
    assert module.build_prediction_inputs(result["patients"], doubled) == result["prediction_inputs"]
    assert module.build_followup_outcomes(result["patients"], doubled) == result["followup_outcomes"]


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_same_day_conflicts_are_rejected_before_history_filter(disease):
    from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
    _, module = core()
    fixture = next(f for f in build_fixed_fixtures()[0] if f["scenario_id"] == "S10"
                   and f["variant"] == "duplicate_day" and f["disease"] == disease)
    for packet in module.build_prediction_inputs(fixture["patients"], fixture["observations"]):
        assert packet["input_status"] == "unavailable"
        assert packet["input_reason"] == "conflicting_history"
        assert packet["history_state"] == "unknown"


@pytest.mark.parametrize("disease, unit", [("ad", "分"), ("fatty_liver", "U/L")])
def test_approved_alias_normalizes_projection_without_rewriting_source(disease, unit):
    from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
    _, module = core()
    fixture = next(f for f in build_fixed_fixtures()[0] if f["scenario_id"] == "S14"
                   and f["variant"] == "approved_alias" and f["disease"] == disease)
    original = deepcopy(fixture)
    packet = module.build_prediction_inputs(fixture["patients"], fixture["observations"])[0]
    assert packet["input_status"] == "available"
    assert all(row["unit"] == unit for row in packet["input_observations"])
    assert fixture == original


@pytest.mark.parametrize("role", ["history", "anchor"])
def test_known_before_measurement_is_not_input_evidence(role):
    from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
    _, module = core()
    fixture = next(f for f in build_fixed_fixtures()[0] if f["scenario_id"] == "S01" and f["variant"] == "base")
    row = next(r for r in fixture["observations"] if r["role"] == role)
    row["known_on"] = "2022-01-01"
    packet = module.build_prediction_inputs(fixture["patients"], fixture["observations"])[0]
    assert row["observation_id"] not in {r["observation_id"] for r in packet["input_observations"]}
    if role == "anchor":
        assert packet["input_status"] == "unavailable"
    else:
        assert packet["history_state"] == "unknown"


def test_expansion_preserves_existing_patients_and_observations():
    Config, module = core()
    small = module.generate_cohort(Config(patients_per_disease=15, challenge_per_disease=5))
    large = module.generate_cohort(Config(patients_per_disease=30, challenge_per_disease=10))
    for name, key in (("patients", "subject_id"), ("observations", "observation_id"),
                      ("prediction_inputs", "sample_id")):
        indexed = {row[key]: row for row in large[name]}
        assert all(indexed[row[key]] == row for row in small[name])


def test_default_cohort_is_bounded_synthetic_and_has_four_tasks():
    Config, module = core()
    result = module.generate_cohort(Config())
    assert len(result["patients"]) == 240
    assert len(result["prediction_inputs"]) == len(result["followup_outcomes"]) == 480
    assert {p["task_id"] for p in result["prediction_inputs"]} == {
        "ad.mmse.6m", "ad.mmse.12m", "fatty_liver.alt.6m", "fatty_liver.alt.12m"}
    for row in result["observations"]:
        assert row["source"]["is_synthetic"] is True
        assert row["unit"] == ("分" if row["indicator"] == "mmse" else "U/L")
        if row["value"] is not None:
            assert row["value"] >= 0
            if row["indicator"] == "mmse":
                assert row["value"] <= 30 and float(row["value"]).is_integer()
    for packet in result["prediction_inputs"]:
        assert packet["input_status"] == "available"
        assert 1 <= len(packet["input_observations"]) <= 7
        for observation in packet["input_observations"]:
            assert observation["measured_on"] <= packet["anchor_date"]
            assert observation["known_on"] <= packet["anchor_date"]
            assert observation["value"] is not None
            assert not {"role", "horizon_months", "observation_status"} & observation.keys()
        assert not {"pool", "mechanism", "actual_date", "nominal_date"} & packet.keys()


def test_future_mutation_cannot_change_either_horizon_input():
    Config, module = core()
    result = module.generate_cohort(Config(patients_per_disease=15, challenge_per_disease=5))
    observations = deepcopy(result["observations"])
    for row in observations:
        if row["role"] == "followup":
            row["value"] = 999999
            row["known_on"] = "2099-01-01"
            row["treatment_change"] = "synthetic future intervention"
    observations = [r for r in observations if r["horizon_months"] != 6]
    assert module.build_prediction_inputs(result["patients"], observations) == result["prediction_inputs"]


def test_zero_history_is_different_from_unknown_or_unavailable_history():
    Config, module = core()
    result = module.generate_cohort(Config(patients_per_disease=15, challenge_per_disease=5))
    patient = deepcopy(result["patients"][0])
    patient["history_coverage"] = "complete"
    rows = [r for r in result["observations"] if r["subject_id"] == patient["subject_id"] and r["role"] == "anchor"]
    assert module.build_prediction_inputs([patient], rows)[0]["history_state"] == "confirmed_none"
    patient["history_coverage"] = "unknown"
    assert module.build_prediction_inputs([patient], rows)[0]["history_state"] == "unknown"
    patient["history_coverage"] = "complete"
    late = {**rows[0], "observation_id": "late", "role": "history", "measured_on": "2022-01-01", "known_on": "2099-01-01"}
    packet = module.build_prediction_inputs([patient], [*rows, late])[0]
    assert packet["history_state"] == "unknown"
    assert len(packet["input_observations"]) == 1


def test_outcomes_distinguish_nominal_offset_missing_and_unknown():
    Config, module = core()
    result = module.generate_cohort(Config())
    states = {r["status"] for r in result["followup_outcomes"]}
    assert states == {"fixture_observed_at_nominal", "pending_window", "confirmed_unobserved", "pending_observation"}
    for row in result["followup_outcomes"]:
        if row["status"] == "fixture_observed_at_nominal":
            assert row["actual_date"] == row["nominal_date"] and row["value"] is not None
        elif row["status"] == "pending_window":
            assert row["actual_date"] != row["nominal_date"] and row["value"] is not None
        else:
            assert row["value"] is None


def test_duplicate_or_invalid_anchor_is_not_silently_selected():
    Config, module = core()
    result = module.generate_cohort(Config(patients_per_disease=15, challenge_per_disease=5))
    patient = result["patients"][0]
    rows = [deepcopy(r) for r in result["observations"] if r["subject_id"] == patient["subject_id"]]
    anchor = next(r for r in rows if r["role"] == "anchor")
    rows.append({**anchor, "observation_id": "conflicting-anchor", "value": 1})
    assert module.build_prediction_inputs([patient], rows)[0]["input_status"] == "unavailable"


def test_reversing_source_order_does_not_change_projection():
    Config, module = core()
    result = module.generate_cohort(Config(patients_per_disease=15, challenge_per_disease=5))
    assert module.build_prediction_inputs(result["patients"][::-1], result["observations"][::-1]) == result["prediction_inputs"]
