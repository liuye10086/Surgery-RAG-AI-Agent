import json
import math

import pytest

from app.services.prediction_calculation_metrics import (
    paired_bootstrap,
    paired_statistics,
    performance_decision,
)


ROWS = [
    {"subject_id": "a", "dependency_group_id": "g1", "actual": 0., "prediction": 10., "baseline": 12.},
    *[{"subject_id": str(i), "dependency_group_id": "g2", "actual": 0., "prediction": 1., "baseline": 2.} for i in range(4)],
]


def test_patient_weighted_paired_statistics_and_group_multiplicity():
    result = paired_statistics(ROWS)
    assert result["mae"] == pytest.approx(2.8)
    assert result["rmse"] == pytest.approx(math.sqrt(20.8))
    assert result["bias"] == pytest.approx(2.8)
    assert result["baseline_mae"] == pytest.approx(4.)
    assert result["mae_gain"] == pytest.approx(1.2)
    assert result["n_patients"] == 5 and result["n_groups"] == 2
    plan = [[0, 0], [1, 1]]
    boot = paired_bootstrap(ROWS, iterations=2, draw_indices=plan)
    assert boot["attempted"] == 2 and boot["draw_indices"] == plan
    assert boot["intervals"]["mae"]["lower"] == pytest.approx(1.225)
    assert boot["intervals"]["mae"]["upper"] == pytest.approx(9.775)
    assert boot["intervals"]["mae_gain"]["lower"] == pytest.approx(1.025)
    assert boot["intervals"]["mae_gain"]["upper"] == pytest.approx(1.975)


def test_calibration_exact_and_constant_prediction_unavailable():
    rows = [dict(subject_id=str(i), dependency_group_id=str(i), actual=1+2*i,
                 prediction=float(i), baseline=0.) for i in range(3)]
    assert paired_statistics(rows)["alpha"] == pytest.approx(1.)
    assert paired_statistics(rows)["beta"] == pytest.approx(2.)
    for row in rows:
        row["prediction"] = 1.
    result = paired_statistics(rows)
    assert result["alpha"] is result["beta"] is None


def test_reject_duplicate_subject_and_invalid_weights():
    with pytest.raises(ValueError):
        paired_statistics([ROWS[0], ROWS[0]])
    with pytest.raises(ValueError):
        paired_statistics(ROWS, weights=[0] * 5)
    with pytest.raises(ValueError):
        paired_statistics(ROWS, weights=[1, 1, True, 1, 1])


def test_invalid_numeric_never_coerced_or_clipped():
    for invalid in (float("nan"), float("inf"), "1", True):
        rows = [dict(row) for row in ROWS]
        rows[0]["prediction"] = invalid
        result = paired_statistics(rows)
        assert result["mae"] is None and result["rmse"] is None
        assert result["baseline_mae"] == 4.
        assert result["mae_gain"] is None and result["unavailable"]


def test_bootstrap_fixed_plan_order_and_no_replacement_for_invalid_draw():
    rows = [dict(row) for row in ROWS]
    rows[0]["prediction"] = float("nan")
    plan = [[0, 0], [1, 1]]
    result = paired_bootstrap(rows, iterations=2, draw_indices=plan)
    assert result["draw_indices"] == plan and result["attempted"] == 2
    assert result["intervals"]["mae"]["status"] == "not_estimable"
    assert result["intervals"]["mae"]["valid"] == 1
    assert result["intervals"]["mae"]["failed"] == 1
    assert result["intervals"]["baseline_mae"]["status"] == "estimated"
    assert paired_bootstrap(ROWS, iterations=5) == paired_bootstrap(list(reversed(ROWS)), iterations=5)
    with pytest.raises(ValueError):
        paired_bootstrap(ROWS, iterations=2, draw_indices=[[0, 0]])
    with pytest.raises(ValueError):
        paired_bootstrap(ROWS, iterations=1, draw_indices=[[0, True]])
    with pytest.raises(ValueError):
        paired_bootstrap(ROWS, iterations=1, draw_indices=[[0, 2]])


def test_single_group_and_empty_statistics_are_not_estimable():
    result = paired_bootstrap(ROWS[:1], iterations=2)
    assert result["attempted"] == 0 and result["status"] == "not_estimable"
    assert result["draw_indices"] == []
    assert paired_statistics([])["mae"] is None


def test_finite_extremes_keep_defined_metrics_and_bootstrap_failures():
    rows = [dict(subject_id="a", dependency_group_id="g1", actual=0.,
                 prediction=1e200, baseline=1e200),
            dict(subject_id="b", dependency_group_id="g2", actual=0.,
                 prediction=-1e200, baseline=1e200)]
    stats = paired_statistics(rows)
    assert stats["mae"] == 1e200 and stats["bias"] == 0.
    assert stats["baseline_mae"] == 1e200 and stats["mae_gain"] == 0.
    assert stats["rmse"] is None and stats["alpha"] is stats["beta"] is None
    result = paired_bootstrap(rows, iterations=2, draw_indices=[[0, 1], [0, 0]])
    assert result["attempted"] == 2 and result["draw_indices"] == [[0, 1], [0, 0]]
    assert result["intervals"]["rmse"]["failed"] == 2
    assert result["intervals"]["mae"]["status"] == "estimated"
    json.dumps(result, allow_nan=False)


def test_weight_sum_and_interval_width_overflow_do_not_raise_or_emit_infinity():
    with pytest.raises(ValueError):
        paired_statistics(ROWS, weights=[1e308] * len(ROWS))
    rows = [dict(subject_id="a", dependency_group_id="g1", actual=0., prediction=-1e308, baseline=0.),
            dict(subject_id="b", dependency_group_id="g2", actual=0., prediction=1e308, baseline=0.)]
    result = paired_bootstrap(rows, iterations=2, draw_indices=[[0, 0], [1, 1]])
    assert result["intervals"]["bias"]["status"] == "not_estimable"
    assert result["intervals"]["bias"]["width"] is None
    json.dumps(result, allow_nan=False)


def test_gain_averages_paired_patient_error_differences_before_rounding():
    rows = [dict(subject_id="a", dependency_group_id="g1", actual=0.,
                 prediction=1e16, baseline=1e16 + 2),
            dict(subject_id="b", dependency_group_id="g2", actual=0.,
                 prediction=1., baseline=2.)]
    assert paired_statistics(rows)["mae_gain"] == 1.5
    assert paired_statistics(rows, weights=[1, 2])["mae_gain"] == pytest.approx(4 / 3)


def test_performance_decision_boundaries_missing_and_json_roundtrip():
    summary = {"n_patients": 5, "n_groups": 2, "mae": 2., "mae_gain": 1.}
    intervals = {name: {"status": "estimated", "lower": low, "upper": high, "width": high-low}
                 for name, low, high in (("mae", 1., 3.), ("mae_gain", 1., 2.))}
    thresholds = {"max_mae": 3., "min_mae_gain": 1., "max_mae_ci_width": 2., "max_gain_ci_width": 1.}
    assert performance_decision(summary, intervals, thresholds, prerequisites=True, complete_output=True)["status"] == "met"
    intervals["mae_gain"]["lower"] = 0.
    assert performance_decision(summary, intervals, thresholds, prerequisites=True, complete_output=True)["status"] == "not_met"
    thresholds["max_mae"] = None
    result = performance_decision(summary, intervals, thresholds, prerequisites=False, complete_output=False)
    assert result["status"] == "not_assessable"
    assert result["missing"] and result["known_failures"]
    json.dumps({"stats": paired_statistics(ROWS), "bootstrap": paired_bootstrap(ROWS, iterations=2), "decision": result}, allow_nan=False)
