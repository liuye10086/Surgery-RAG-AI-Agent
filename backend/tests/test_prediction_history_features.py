from copy import deepcopy
import math

import pytest

from app.services.prediction_calculation import project_calculation_inputs
from app.services.synthetic_prediction_cases import build_prediction_inputs
from app.services.synthetic_prediction_fixtures import build_fixed_fixtures


def packet(*, observations=None, history_state="observed", history_coverage="complete",
           input_status="available", input_reason=None, sample_id="sample-1"):
    if observations is None:
        observations = [
            observation("history-1", "2026-01-01", 10.0),
            observation("history-2", "2026-01-11", 12.0),
            observation("anchor", "2026-01-21", 14.0),
        ]
    return {
        "sample_id": sample_id,
        "subject_id": "synthetic-subject-1",
        "dependency_group_id": "synthetic-group-1",
        "task_id": "ad.mmse.6m",
        "horizon_months": 6,
        "anchor_date": "2026-01-21",
        "anchor_observation_id": "anchor" if input_status == "available" else None,
        "input_observations": observations,
        "input_status": input_status,
        "input_reason": input_reason,
        "history_coverage": history_coverage,
        "history_state": history_state,
        "source": {
            "is_synthetic": True,
            "source_kind": "synthetic",
            "generator_version": "synthetic-prediction.v1",
            "run_id": "test-only",
        },
    }


def observation(observation_id, measured_on, value, *, known_on=None, method="fixture", unit="分"):
    return {
        "observation_id": observation_id,
        "indicator": "mmse" if unit == "分" else "alt",
        "measured_on": measured_on,
        "known_on": known_on or measured_on,
        "value": value,
        "unit": unit,
        "method": method,
    }


def project(packets):
    from app.services.prediction_history_features import project_history_features

    return project_history_features(packets)


def test_literal_ols_uses_all_history_and_actual_nonuniform_days():
    raw = packet(observations=[
        observation("history-1", "2026-01-01", 10.0),
        observation("history-2", "2026-01-02", 20.0),
        observation("anchor", "2026-01-21", 30.0),
    ])

    row = project([raw])[0]

    # x=(-20,-19,0), y=(10,20,30): means=(-13,20), slope=200/254.
    assert row["history_status"] == "available"
    assert row["history_reason"] is None
    assert row["prior_value"] == 20.0
    assert row["slope_per_day"] == pytest.approx(100 / 127)
    assert (row["n_pre"], row["span_pre_days"]) == (2, 20)


def test_plan_literal_projection_is_point_two_per_day():
    row = project([packet()])[0]
    assert (row["prior_value"], row["n_pre"], row["span_pre_days"]) == (12.0, 2, 20)
    assert row["slope_per_day"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("state", "coverage", "observations"),
    [
        ("unknown", "unknown", [observation("anchor", "2026-01-21", 14.0)]),
        ("unknown", "complete", [observation("history", "2026-01-01", 10.0),
                                   observation("anchor", "2026-01-21", 14.0)]),
        ("observed", "unknown", [observation("history", "2026-01-01", 10.0),
                                  observation("anchor", "2026-01-21", 14.0)]),
        ("confirmed_none", "complete", [observation("anchor", "2026-01-21", 14.0)]),
        # The public schema permits this contradictory state; it must not qualify for H.
        ("confirmed_none", "complete", [observation("history", "2026-01-01", 10.0),
                                           observation("anchor", "2026-01-21", 14.0)]),
        ("observed", "complete", [observation("anchor", "2026-01-21", 14.0)]),
    ],
)
def test_unknown_zero_and_unusable_history_abstain_without_fabricating_values(state, coverage, observations):
    row = project([packet(history_state=state, history_coverage=coverage, observations=observations)])[0]
    assert row["history_status"] == "abstain"
    assert row["history_reason"]
    assert row["prior_value"] is None
    assert row["slope_per_day"] is None


def test_unavailable_anchor_abstains_and_preserves_base_projection():
    raw = packet(observations=[], history_state="unknown", history_coverage="unknown",
                 input_status="unavailable", input_reason="anchor_unavailable")
    base = project_calculation_inputs([raw])[0]
    row = project([raw])[0]
    assert all(row[key] == value for key, value in base.items())
    assert (row["history_status"], row["history_reason"]) == ("abstain", "anchor_not_available")
    assert row["prior_value"] is row["slope_per_day"] is None


def test_available_projection_preserves_every_base_field():
    raw = packet()
    base = project_calculation_inputs([raw])[0]
    row = project([raw])[0]
    assert {key: row[key] for key in base} == base


@pytest.mark.parametrize("mutation", ["future", "late_known", "same_day", "method", "unit", "nonfinite",
                                      "missing_anchor"])
def test_existing_input_boundary_violations_remain_rejected(mutation):
    raw = packet()
    if mutation == "future":
        raw["input_observations"][0]["measured_on"] = "2026-01-22"
        raw["input_observations"][0]["known_on"] = "2026-01-22"
    elif mutation == "late_known":
        raw["input_observations"][0]["known_on"] = "2026-01-22"
    elif mutation == "same_day":
        raw["input_observations"][0]["measured_on"] = "2026-01-21"
        raw["input_observations"][0]["known_on"] = "2026-01-21"
    elif mutation == "method":
        raw["input_observations"][0]["method"] = "other"
    elif mutation == "unit":
        raw["input_observations"][0]["unit"] = "U/L"
    elif mutation == "missing_anchor":
        raw["anchor_observation_id"] = "missing"
    else:
        raw["input_observations"][0]["value"] = math.inf

    with pytest.raises(ValueError):
        project([raw])


def test_future_outcome_changes_cannot_change_history_features():
    fixtures = build_fixed_fixtures()[0]
    base = next(row for row in fixtures
                if (row["scenario_id"], row["variant"], row["disease"]) == ("S12", "base", "ad"))
    changed = next(row for row in fixtures
                   if (row["scenario_id"], row["variant"], row["disease"])
                   == ("S12", "future_changed", "ad"))
    assert project(build_prediction_inputs(base["patients"], base["observations"])) == project(
        build_prediction_inputs(changed["patients"], changed["observations"])
    )


def test_sorting_is_deterministic_and_inputs_are_not_mutated():
    first = packet(sample_id="b")
    first["input_observations"].reverse()
    second = packet(sample_id="a")
    supplied = [first, second]
    before = deepcopy(supplied)

    rows = project(supplied)

    assert [row["sample_id"] for row in rows] == ["a", "b"]
    assert rows[0]["prior_value"] == rows[1]["prior_value"] == 12.0
    assert supplied == before


def test_finite_extreme_ols_overflow_is_reported_as_error():
    raw = packet(observations=[
        observation("history-1", "2026-01-01", 0.0, unit="U/L"),
        observation("history-2", "2026-01-11", 1e308, unit="U/L"),
        observation("anchor", "2026-01-21", 0.0, unit="U/L"),
    ])
    raw["task_id"] = "fatty_liver.alt.6m"

    row = project([raw])[0]

    assert row["history_status"] == "error"
    assert row["history_reason"] == "history_calculation_error"
    assert row["prior_value"] is None
    assert row["slope_per_day"] is None
