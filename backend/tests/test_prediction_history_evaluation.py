import pytest

from app.services.prediction_calculation import TASKS


TASK = "ad.mmse.6m"


def test_literal_paired_arithmetic_names_reference_and_gain():
    from app.services.prediction_history_evaluation import evaluate_history_role

    samples = [
        {
            "sample_id": f"s{index}",
            "subject_id": f"p{index}",
            "dependency_group_id": f"g{index}",
            "task_id": TASK,
            "pool": "development_pool",
            "evaluation_role": "internal_validation",
            "anchor_status": "eligible",
            "label_status": "valid",
            "actual": actual,
            "history_status": "available",
            "history_reason": None,
        }
        for index, actual in enumerate((10.0, 20.0))
    ]
    predictions = []
    for family in ("ridge", "random_forest"):
        for branch in (
            "anchor_all",
            "anchor_history",
            "schedule_history",
            "value_history",
            "value_schedule_history",
        ):
            for sample, value in zip(samples, (11.0, 18.0)):
                predictions.append(
                    {
                        "sample_id": sample["sample_id"],
                        "task_id": TASK,
                        "model_id": f"{family}:history_v1:{branch}",
                        "status": "valid",
                        "value": value,
                        "reason": None,
                    }
                )
    baselines = []
    for sample, last in zip(samples, (13.0, 16.0)):
        for model_id in ("last_value", "history_trend"):
            baselines.append(
                {
                    "sample_id": sample["sample_id"],
                    "model_id": model_id,
                    "status": "valid",
                    "value": last,
                    "reason": None,
                }
            )

    result = evaluate_history_role(samples, predictions, baselines, role="internal_validation")
    comparison = next(
        row
        for row in result["evaluation"]["comparisons"]
        if row["task_id"] == TASK
        and row["family"] == "ridge"
        and row["comparison_name"] == "value_history_vs_last_value"
        and row["scope"] == "original"
    )

    assert comparison["candidate_model_id"] == "ridge:history_v1:value_history"
    assert comparison["reference_model_id"] == "last_value"
    assert comparison["gain_name"] == "mae_gain_reference_minus_candidate"
    assert comparison["statistics"]["mae"] == 1.5
    assert comparison["statistics"]["reference_mae"] == 3.5
    assert comparison["statistics"]["mae_gain_reference_minus_candidate"] == 2.0
    assert comparison["statistics"]["bias"] == -0.5
    assert comparison["uncertainty_scope"] == "descriptive_only"
    assert comparison["clinical_status"] == "not_assessable"
    assert len(result["evaluation"]["comparisons"]) == 160


BRANCHES = (
    "anchor_all",
    "anchor_history",
    "schedule_history",
    "value_history",
    "value_schedule_history",
)


def evaluation_rows(*, role="internal_validation", statuses=None):
    pool = "challenge_pool" if role == "challenge" else "development_pool"
    statuses = statuses or {}
    samples, predictions, baselines = [], [], []
    specifications = (
        ("s0", "p0", "g0", 10.0, "available", "valid"),
        ("s1", "p1", "g1", 20.0, "available", "valid"),
        ("s2", "p2", "g1", 30.0, "available", "valid"),
        ("s3", "p3", "g3", None, "available", "absent"),
        ("s4", "p4", "g4", 15.0, "abstain", "valid"),
    )
    for sid, subject, group, actual, history_status, label_status in specifications:
        samples.append({
            "sample_id": sid, "subject_id": subject, "dependency_group_id": group,
            "task_id": TASK, "pool": pool, "evaluation_role": role,
            "anchor_status": "eligible", "label_status": label_status, "actual": actual,
            "history_status": history_status,
            "history_reason": None if history_status == "available" else "history_not_observed",
        })
        for family in ("ridge", "random_forest"):
            for branch in BRANCHES:
                status = statuses.get((sid, family, branch), "valid")
                predictions.append({
                    "sample_id": sid, "task_id": TASK,
                    "model_id": f"{family}:history_v1:{branch}", "status": status,
                    "value": actual + 1 if status == "valid" and actual is not None else
                             (16.0 if status == "valid" else None),
                    "reason": None if status == "valid" else "controlled_failure",
                })
        for model_id in ("last_value", "history_trend"):
            baselines.append({
                "sample_id": sid, "task_id": TASK, "model_id": model_id,
                "status": "valid", "value": actual + 3 if actual is not None else 16.0,
                "reason": None,
            })
    return samples, predictions, baselines


def find(result, name, *, family="ridge", scope="original", task=TASK):
    return next(row for row in result["evaluation"]["comparisons"]
                if row["task_id"] == task and row["family"] == family
                and row["comparison_name"] == name and row["scope"] == scope)


def test_all_planned_comparisons_preserve_pair_order_h_eligibility_and_missing_labels():
    result = __import__(
        "app.services.prediction_history_evaluation", fromlist=["evaluate_history_role"]
    ).evaluate_history_role(*evaluation_rows(), role="internal_validation")
    originals = [row for row in result["evaluation"]["comparisons"]
                 if row["task_id"] == TASK and row["family"] == "ridge"
                 and row["scope"] == "original"]
    assert [row["comparison_name"] for row in originals] == [
        *(f"{branch}_vs_last_value" for branch in BRANCHES),
        "history_trend_vs_last_value",
        "schedule_history_vs_anchor_history",
        "value_history_vs_anchor_history",
        "value_schedule_history_vs_value_history",
        "value_schedule_history_vs_schedule_history",
    ]
    anchor = find(result, "anchor_all_vs_last_value")
    history = find(result, "value_history_vs_anchor_history")
    assert anchor["counts"]["N_branch_eligible"] == 5
    assert history["counts"]["N_branch_eligible"] == 4
    assert history["counts"]["N_label_valid"] == 3
    assert history["counts"]["N_label_absent"] == 1
    assert history["counts"]["N_pair_valid"] == 3
    assert [row["sample_id"] for row in result["paired_rows"]
            if row["comparison_id"] == history["comparison_id"]] == ["s0", "s1", "s2"]
    assert history["statistics"]["mae"] == 1.0
    assert history["statistics"]["reference_mae"] == 1.0
    assert history["statistics"]["mae_gain_reference_minus_candidate"] == 0.0
    assert history["unit"] == "分"


def test_each_prespecified_h_comparison_has_the_fixed_reference_and_signed_gain():
    from app.services.prediction_history_evaluation import evaluate_history_role
    samples, predictions, baselines = evaluation_rows()
    candidate_values = {
        "anchor_history": {"s0": 11.0, "s1": 18.0, "s2": 31.0},
        "schedule_history": {"s0": 10.0, "s1": 19.0, "s2": 32.0},
        "value_history": {"s0": 14.0, "s1": 15.0, "s2": 33.0},
        "value_schedule_history": {"s0": 12.0, "s1": 18.0, "s2": 34.0},
    }
    for row in predictions:
        branch = row["model_id"].rsplit(":", 1)[-1]
        if row["model_id"].startswith("ridge:") and branch in candidate_values \
                and row["sample_id"] in candidate_values[branch]:
            row["value"] = candidate_values[branch][row["sample_id"]]
    last = {"s0": 13.0, "s1": 16.0, "s2": 36.0}
    trend = {"s0": 12.0, "s1": 17.0, "s2": 33.0}
    for row in baselines:
        values = last if row["model_id"] == "last_value" else trend
        if row["sample_id"] in values:
            row["value"] = values[row["sample_id"]]
    result = evaluate_history_role(samples, predictions, baselines, role="internal_validation")
    expected = {
        "history_trend_vs_last_value": ("history_trend", "last_value", 5 / 3),
        "schedule_history_vs_anchor_history": (
            "ridge:history_v1:schedule_history", "ridge:history_v1:anchor_history", 1 / 3),
        "value_history_vs_anchor_history": (
            "ridge:history_v1:value_history", "ridge:history_v1:anchor_history", -8 / 3),
        "value_schedule_history_vs_value_history": (
            "ridge:history_v1:value_schedule_history", "ridge:history_v1:value_history", 4 / 3),
        "value_schedule_history_vs_schedule_history": (
            "ridge:history_v1:value_schedule_history", "ridge:history_v1:schedule_history", -5 / 3),
    }
    for name, (candidate, reference, gain) in expected.items():
        comparison = find(result, name)
        assert comparison["candidate_model_id"] == candidate
        assert comparison["reference_model_id"] == reference
        assert comparison["statistics"]["mae_gain_reference_minus_candidate"] == pytest.approx(gain)
        assert [row["sample_id"] for row in result["paired_rows"]
                if row["comparison_id"] == comparison["comparison_id"]] == ["s0", "s1", "s2"]


def test_missing_output_shrinks_common_set_but_remains_visible_and_incomplete():
    statuses = {("s1", "ridge", "value_history"): "error"}
    samples, predictions, baselines = evaluation_rows(statuses=statuses)
    predictions = [row for row in predictions if not (
        row["sample_id"] == "s2" and row["model_id"] == "ridge:history_v1:schedule_history"
    )]
    from app.services.prediction_history_evaluation import evaluate_history_role
    result = evaluate_history_role(samples, predictions, baselines, role="internal_validation")
    original = find(result, "value_history_vs_anchor_history")
    common = find(result, "value_history_vs_anchor_history", scope="common_complete")
    assert original["joint_states"]["candidate_unavailable"] == 1
    assert original["counts"]["N_pred_error"] == 1
    assert original["counts"]["N_pair_valid"] == 2
    assert common["counts"]["N_common_complete"] == 1
    assert common["counts"]["N_common_excluded"] == 3
    assert common["counts"]["N_common_excluded_due_to_output"] == 2
    assert common["counts"]["N_original_pred_error"] == 1
    assert not original["complete_output"] and not common["complete_output"]
    unaffected = find(result, "anchor_history_vs_last_value", scope="common_complete")
    assert unaffected["counts"]["N_original_pred_error"] == 0
    assert unaffected["common_scope_limited"] and not unaffected["complete_output"]


@pytest.mark.parametrize("failed_branch", ["value_history", "anchor_history"])
def test_non_h_explicit_candidate_or_reference_error_makes_h_comparison_incomplete(failed_branch):
    from app.services.prediction_history_evaluation import evaluate_history_role
    samples, predictions, baselines = evaluation_rows()
    for row in predictions:
        if row["sample_id"] == "s4" and row["model_id"].startswith("ridge:"):
            branch = row["model_id"].rsplit(":", 1)[-1]
            if branch in {"value_history", "anchor_history"}:
                row.update(status="abstain", value=None, reason="history_not_observed")
            if branch == failed_branch:
                row.update(status="error", value=None, reason="controlled_failure")
    result = evaluate_history_role(samples, predictions, baselines, role="internal_validation")
    comparison = find(result, "value_history_vs_anchor_history")
    count_key = "N_all_pred_error" if failed_branch == "value_history" else "N_all_reference_error"
    assert comparison["counts"][count_key] == 1
    assert not comparison["complete_output"]


def test_non_h_expected_abstentions_do_not_make_h_comparison_incomplete():
    from app.services.prediction_history_evaluation import evaluate_history_role
    samples, predictions, baselines = evaluation_rows()
    for row in predictions:
        if row["sample_id"] == "s4" and row["model_id"] in {
            "ridge:history_v1:value_history", "ridge:history_v1:anchor_history"
        }:
            row.update(status="abstain", value=None, reason="history_not_observed")
    comparison = find(
        evaluate_history_role(samples, predictions, baselines, role="internal_validation"),
        "value_history_vs_anchor_history",
    )
    assert comparison["counts"]["N_all_pred_abstain"] == 1
    assert comparison["counts"]["N_all_reference_abstain"] == 1
    assert comparison["complete_output"]


def test_full_role_queue_filters_requested_role_and_rejects_groups_crossing_roles():
    from copy import deepcopy
    from app.services.prediction_history_evaluation import evaluate_history_role

    samples, predictions, baselines = evaluation_rows()
    training = deepcopy(samples[0])
    training.update(sample_id="training-sample", subject_id="training-patient",
                    dependency_group_id="training-group", evaluation_role="training")
    samples.append(training)
    for row in list(predictions):
        if row["sample_id"] == "s0":
            predictions.append({**row, "sample_id": "training-sample"})
    for row in list(baselines):
        if row["sample_id"] == "s0":
            baselines.append({**row, "sample_id": "training-sample"})
    scored = evaluate_history_role(samples, predictions, baselines, role="internal_validation")
    assert find(scored, "anchor_all_vs_last_value")["counts"]["N_patient"] == 5
    samples[-1]["dependency_group_id"] = "g0"
    with pytest.raises(ValueError, match="dependency_crosses_partitions"):
        evaluate_history_role(samples, predictions, baselines, role="internal_validation")


def test_zero_denominators_constant_extreme_and_all_output_range_counts():
    from app.services.prediction_history_evaluation import evaluate_history_role
    empty = evaluate_history_role([], [], [], role="training")
    assert len(empty["evaluation"]["comparisons"]) == 160
    assert all(row["statistics"]["mae"] is None for row in empty["evaluation"]["comparisons"])
    assert all(row["coverage"]["paired"]["reason"] == "zero_denominator"
               for row in empty["evaluation"]["comparisons"])
    samples, predictions, baselines = evaluation_rows()
    for row in predictions:
        if row["model_id"] == "ridge:history_v1:value_history":
            row["value"] = 1e200 if row["sample_id"] == "s0" else 40.0
    result = evaluate_history_role(samples, predictions, baselines, role="internal_validation")
    comparison = find(result, "value_history_vs_last_value")
    assert comparison["statistics"]["rmse"] is None
    assert comparison["statistics"]["mae"] > 1e199
    assert comparison["counts"]["N_all_candidate_out_of_range"] == 5


def test_challenge_bootstrap_reuses_plan_for_same_patients_not_only_same_groups_and_keeps_failures():
    from app.services.prediction_history_evaluation import evaluate_history_role
    samples, predictions, baselines = evaluation_rows(role="challenge")
    result = evaluate_history_role(samples, predictions, baselines, role="challenge")
    first = find(result, "value_history_vs_last_value")
    second = find(result, "value_history_vs_anchor_history")
    assert first["bootstrap_plan_id"] == second["bootstrap_plan_id"]
    plan = result["bootstrap_plans"][first["bootstrap_plan_id"]]
    assert plan["ordered_groups"] == ["g0", "g1"]
    assert len(plan["draw_indices"]) == 2000
    assert all(len(draw) == 2 for draw in plan["draw_indices"])
    assert not {"status", "valid", "failed"} & plan.keys()
    assert first["statistics"]["n_patients"] == 3
    assert first["statistics"]["n_groups"] == 2
    assert first["statistics"]["mae"] == 1.0
    assert first["intervals"]["mae"]["lower"] == first["intervals"]["mae"]["upper"] == 1.0
    for row in predictions:
        if row["model_id"] == "ridge:history_v1:value_history":
            row["value"] = -1e200
    failed = find(evaluate_history_role(samples, predictions, baselines, role="challenge"),
                  "value_history_vs_last_value")
    assert failed["intervals"]["rmse"]["attempted"] == 2000
    assert failed["intervals"]["rmse"]["valid"] == 0
    assert failed["intervals"]["rmse"]["failed"] == 2000
    assert failed["intervals"]["rmse"]["status"] == "not_estimable"


def test_same_groups_with_different_paired_patients_get_distinct_plans():
    from app.services.prediction_history_evaluation import evaluate_history_role
    samples, predictions, baselines = evaluation_rows(role="challenge")
    for row in predictions:
        if row["model_id"] == "ridge:history_v1:value_history" and row["sample_id"] == "s1":
            row.update(status="error", value=None, reason="controlled")
        if row["model_id"] == "ridge:history_v1:schedule_history" and row["sample_id"] == "s2":
            row.update(status="error", value=None, reason="controlled")
    result = evaluate_history_role(samples, predictions, baselines, role="challenge")
    value = find(result, "value_history_vs_last_value")
    schedule = find(result, "schedule_history_vs_last_value")
    assert value["counts"]["N_pair_valid"] == schedule["counts"]["N_pair_valid"] == 2
    assert result["bootstrap_plans"][value["bootstrap_plan_id"]]["ordered_groups"] == ["g0", "g1"]
    assert result["bootstrap_plans"][schedule["bootstrap_plan_id"]]["ordered_groups"] == ["g0", "g1"]
    assert value["bootstrap_plan_id"] != schedule["bootstrap_plan_id"]


def test_empty_challenge_plans_are_task_bound_and_explicit_wrong_baseline_task_rejected():
    from app.services.prediction_history_evaluation import evaluate_history_role
    empty = evaluate_history_role([], [], [], role="challenge")
    ids = {row["task_id"]: row["bootstrap_plan_id"]
           for row in empty["evaluation"]["comparisons"]
           if row["family"] == "ridge" and row["scope"] == "original"
           and row["comparison_name"] == "anchor_all_vs_last_value"}
    assert len(set(ids.values())) == len(TASKS)
    samples, predictions, baselines = evaluation_rows()
    baselines[0]["task_id"] = "fatty_liver.alt.6m"
    with pytest.raises(ValueError, match="invalid_prediction_identity"):
        evaluate_history_role(samples, predictions, baselines, role="internal_validation")


def test_t1_projection_joins_existing_engineering_sample_shape_before_evaluation():
    from app.services.prediction_calculation import build_engineering_samples
    from app.services.prediction_history_features import project_history_features
    from app.services.synthetic_prediction_cases import build_followup_outcomes, build_prediction_inputs
    from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
    from app.services.prediction_history_evaluation import evaluate_history_role

    fixture = build_fixed_fixtures()[0]
    case = next(row for row in fixture
                if row["scenario_id"] == "S12" and row["variant"] == "base" and row["disease"] == "ad")
    packets = build_prediction_inputs(case["patients"], case["observations"])
    projected = project_history_features(packets)
    audit = [{"subject_id": patient["subject_id"],
              "dependency_group_id": patient["dependency_group_id"], "pool": "challenge_pool"}
             for patient in case["patients"]]
    engineering = build_engineering_samples(
        case["patients"], packets,
        build_followup_outcomes(case["patients"], case["observations"]), audit,
    )
    feature_map = {row["sample_id"]: row for row in projected}
    samples = [{
        **row,
        "history_status": feature_map[row["sample_id"]]["history_status"],
        "history_reason": feature_map[row["sample_id"]]["history_reason"],
        "evaluation_role": "challenge",
    } for row in engineering]
    predictions, baselines = [], []
    for row in samples:
        for family in ("ridge", "random_forest"):
            for branch in BRANCHES:
                predictions.append({"sample_id": row["sample_id"], "task_id": row["task_id"],
                                    "model_id": f"{family}:history_v1:{branch}",
                                    "status": "valid", "value": row["anchor_value"], "reason": None})
        for model_id in ("last_value", "history_trend"):
            baselines.append({"sample_id": row["sample_id"], "task_id": row["task_id"],
                              "model_id": model_id, "status": "valid",
                              "value": row["anchor_value"], "reason": None})
    result = evaluate_history_role(samples, predictions, baselines, role="challenge")
    assert result["evaluation"]["source_kind"] == "synthetic"
    assert all(row["history_status"] in {"available", "error"} for row in samples)
    assert any(row["counts"]["N_patient"] for row in result["evaluation"]["comparisons"])


def test_aggregate_fixed_catalog_exposes_missing_and_invalid_seed_scores_and_rejects_tampering():
    from copy import deepcopy
    from app.services.prediction_history_evaluation import aggregate_history_runs, evaluate_history_role

    scored = evaluate_history_role(*evaluation_rows(), role="internal_validation")
    runs = [{"seed": seed, "evaluations": [deepcopy(scored)]}
            for seed in (20260914, 20260915)]
    target = find(runs[1]["evaluations"][0], "value_history_vs_last_value")
    target["statistics"]["mae"] = None
    target["statistics"]["rmse"] = None
    summaries = aggregate_history_runs(runs)
    assert len(summaries) == 480
    summary = next(row for row in summaries if row["evaluation_role"] == "internal_validation"
                   and row["task_id"] == TASK and row["family"] == "ridge"
                   and row["comparison_name"] == "value_history_vs_last_value"
                   and row["scope"] == "original")
    assert summary["seeds"] == [20260914, 20260915]
    assert summary["missing_seeds"] == [20260916]
    assert summary["n_present_seeds"] == 2
    assert summary["n_effective_seeds"] == 1
    assert summary["metrics"]["mae"]["n_valid"] == 1
    assert summary["gain_direction"] == "positive"
    assert summary["incomplete"] and not summary["complete"]
    tampered = deepcopy(runs[:1])
    find(tampered[0]["evaluations"][0], "value_history_vs_last_value")["reference_model_id"] = "history_trend"
    with pytest.raises(ValueError, match="unknown_or_duplicate_history_comparison"):
        aggregate_history_runs(tampered)


def test_aggregate_large_finite_values_never_emit_nonfinite_numbers():
    import json
    from copy import deepcopy
    from app.services.prediction_history_evaluation import aggregate_history_runs, evaluate_history_role
    scored = evaluate_history_role(*evaluation_rows(), role="internal_validation")
    for row in scored["evaluation"]["comparisons"]:
        row["statistics"]["mae"] = 1e308
    result = aggregate_history_runs([
        {"seed": seed, "evaluations": [deepcopy(scored)]} for seed in (20260914, 20260915, 20260916)
    ])
    assert len(result) == 480
    target = next(row for row in result if row["evaluation_role"] == "internal_validation")
    assert target["metrics"]["mae"]["mean"] == 1e308
    assert target["n_effective_seeds"] == 3
    json.dumps(result, allow_nan=False)
