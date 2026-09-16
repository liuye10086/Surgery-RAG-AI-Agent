from copy import deepcopy
import math

import pytest

from app.services.prediction_calculation import TASKS


def rows():
    features, samples = [], []
    for task in TASKS:
        for suffix, role, pool, anchor, actual, history_status in (
            ("a", "training", "development_pool", 0.0, 1.0, "available"),
            ("b", "training", "development_pool", 2.0, 3.0, "available"),
            ("x", "training", "development_pool", 4.0, 5.0, "abstain"),
            ("v", "internal_validation", "development_pool", 3.0, 4.0, "available"),
            ("c", "challenge", "challenge_pool", 5.0, 6.0, "available"),
        ):
            sample_id = f"{task}:{suffix}"
            feature = {
                "sample_id": sample_id, "subject_id": sample_id,
                "dependency_group_id": sample_id, "task_id": task,
                "horizon_months": int(task.rsplit(".", 1)[1][:-1]),
                "anchor_date": "2026-01-01", "source": {"source_kind": "synthetic"},
                "pool": pool, "evaluation_role": role, "input_status": "available",
                "history_status": history_status,
                "history_reason": None if history_status == "available" else "history_not_observed",
                "anchor_value": anchor, "prior_value": anchor - 1.0,
                "slope_per_day": anchor / 10.0, "n_pre": 2, "span_pre_days": 20,
            }
            features.append(feature)
            if role == "training":
                samples.append({key: feature[key] for key in (
                    "sample_id", "subject_id", "dependency_group_id", "task_id",
                    "horizon_months", "anchor_date", "source", "pool", "evaluation_role"
                )} | {"anchor_status": "eligible", "label_status": "valid", "actual": actual})
    return features, samples


def training():
    from app.services import prediction_history_training
    return prediction_history_training


def model(result, task, model_id):
    return next(row for row in result["models"]
                if row["task_id"] == task and row["model_id"] == model_id)


def prediction(rows_, sample_id, model_id):
    return next(row for row in rows_
                if row["sample_id"] == sample_id and row["model_id"] == model_id)


def test_plan_literal_ridge_standardization_and_prediction():
    module = training()
    features, samples = rows()
    for row in samples:
        if row["sample_id"].endswith(":x"):
            row.update(label_status="absent", actual=None)
    fitted = module.fit_history_models(features, samples)
    ridge = model(fitted, TASKS[0], module.history_model_id("ridge", "anchor_all"))
    assert ridge["mean"] == [1.0]
    assert ridge["std"] == [1.0]
    assert ridge["scale"] == [1.0]
    assert ridge["coef"] == pytest.approx([2 / 3])
    assert ridge["intercept"] == pytest.approx(2.0)
    probe = deepcopy(features[0])
    probe.update(sample_id="probe", subject_id="probe", dependency_group_id="probe",
                 anchor_value=3.0)
    for key in ("pool", "evaluation_role"):
        probe.pop(key)
    result = prediction(module.predict_history_models([probe], fitted["models"], fitted["estimators"]),
                        "probe", module.history_model_id("ridge", "anchor_all"))
    assert result["value"] == pytest.approx(10 / 3)


def test_all_attempts_and_four_history_branches_share_training_identity():
    module = training()
    fitted = module.fit_history_models(*rows())
    assert len(fitted["models"]) == 40
    assert len(fitted["estimators"]) == 40
    assert len({row["model_id"] for row in fitted["models"]}) == 10
    for task in TASKS:
        for family in module.FAMILIES:
            records = [model(fitted, task, module.history_model_id(family, branch))
                       for branch in module.HISTORY_BRANCHES]
            assert len({tuple(row["training_sample_ids"]) for row in records}) == 1
            assert len({row["training_identity_sha256"] for row in records}) == 1
            assert len({row["training_target_sha256"] for row in records}) == 1
            assert all(row["training_sample_ids"] == [f"{task}:a", f"{task}:b"] for row in records)


def test_non_history_only_trains_anchor_all_and_unlabelled_inputs_are_predicted():
    module = training()
    features, samples = rows()
    fitted = module.fit_history_models(features, samples)
    all_model = model(fitted, TASKS[0], module.history_model_id("ridge", "anchor_all"))
    history_model = model(fitted, TASKS[0], module.history_model_id("ridge", "anchor_history"))
    assert f"{TASKS[0]}:x" in all_model["training_sample_ids"]
    assert f"{TASKS[0]}:x" not in history_model["training_sample_ids"]
    predictions = module.predict_history_models(features, fitted["models"], fitted["estimators"])
    assert prediction(predictions, f"{TASKS[0]}:v", all_model["model_id"])["status"] == "valid"
    assert prediction(predictions, f"{TASKS[0]}:x", all_model["model_id"])["status"] == "valid"
    assert prediction(predictions, f"{TASKS[0]}:x", history_model["model_id"])["status"] == "abstain"


def test_validation_and_challenge_changes_do_not_affect_fit_and_training_y_only_affects_y_dependent_fields():
    module = training()
    features, samples = rows()
    baseline = module.fit_history_models(features, samples)
    changed_features = deepcopy(features)
    for row in changed_features:
        if row["evaluation_role"] != "training":
            row.update(anchor_value=9999.0, prior_value=-9999.0, slope_per_day=999.0)
    assert module.fit_history_models(changed_features, deepcopy(samples))["models"] == baseline["models"]
    changed_samples = deepcopy(samples)
    changed_samples[0]["actual"] = 9.0
    relabelled = module.fit_history_models(features, changed_samples)
    before = model(baseline, TASKS[0], module.history_model_id("ridge", "anchor_all"))
    after = model(relabelled, TASKS[0], module.history_model_id("ridge", "anchor_all"))
    assert (after["mean"], after["std"], after["scale"]) == (before["mean"], before["std"], before["scale"])
    assert after["training_identity_sha256"] == before["training_identity_sha256"]
    assert (after["coef"], after["intercept"], after["training_data_sha256"]) != \
           (before["coef"], before["intercept"], before["training_data_sha256"])


def test_history_calculation_error_preserves_h_identity_but_only_slope_branches_fail():
    module = training()
    features, samples = rows()
    bad = next(row for row in features if row["sample_id"] == f"{TASKS[0]}:a")
    bad.update(history_status="error", history_reason="history_calculation_error",
               prior_value=None, slope_per_day=None)
    fitted = module.fit_history_models(features, samples)
    ids = {tuple(model(fitted, TASKS[0], module.history_model_id("ridge", branch))["training_sample_ids"])
           for branch in module.HISTORY_BRANCHES}
    assert ids == {(f"{TASKS[0]}:a", f"{TASKS[0]}:b")}
    assert model(fitted, TASKS[0], module.history_model_id("ridge", "anchor_history"))["status"] == "fitted"
    assert model(fitted, TASKS[0], module.history_model_id("ridge", "schedule_history"))["status"] == "fitted"
    for branch in ("value_history", "value_schedule_history"):
        assert model(fitted, TASKS[0], module.history_model_id("ridge", branch))["reason"] == "nonfinite_training_data"
    predicted = module.predict_history_models([bad], fitted["models"], fitted["estimators"])
    assert {row["status"] for row in predicted if row["model_id"].endswith(":anchor_all")} == {"valid"}
    for branch in ("anchor_history", "schedule_history"):
        assert prediction(predicted, bad["sample_id"], module.history_model_id("ridge", branch))["status"] == "valid"
    for branch in ("value_history", "value_schedule_history"):
        assert prediction(predicted, bad["sample_id"], module.history_model_id("ridge", branch))["status"] == "error"


@pytest.mark.parametrize("mutation,reason", [
    (lambda f, s: f[0].update(evaluation_role="internal_validation"), "sample_role_mismatch"),
    (lambda f, s: s[0].update(evaluation_role="internal_validation"), "training_role_required"),
    (lambda f, s: s[0].update(pool="challenge_pool"), "training_role_required"),
    (lambda f, s: f[1].update(subject_id=f[0]["subject_id"]), "duplicate_analysis_patient"),
    (lambda f, s: f[-1].update(dependency_group_id=f[0]["dependency_group_id"]), "dependency_crosses_partitions"),
])
def test_training_role_identity_and_partition_violations_are_rejected(mutation, reason):
    module = training()
    features, samples = rows()
    mutation(features, samples)
    with pytest.raises(ValueError, match=reason):
        module.fit_history_models(features, samples)


def test_training_role_features_and_samples_must_have_the_same_identity_set():
    module = training()
    features, samples = rows()
    with pytest.raises(ValueError, match="training_sample_set_mismatch"):
        module.fit_history_models(features, samples[:-1])


def test_invalid_history_status_and_subject_group_change_are_rejected():
    module = training()
    features, samples = rows()
    features[0]["history_status"] = "unknown"
    with pytest.raises(ValueError, match="invalid_history_status"):
        module.fit_history_models(features, samples)
    with pytest.raises(ValueError, match="invalid_history_status"):
        module.predict_history_models([features[0]], [], {})
    features, samples = rows()
    same_subject = next(row for row in features if row["sample_id"] == f"{TASKS[1]}:a")
    same_subject["subject_id"] = features[0]["subject_id"]
    same_subject["dependency_group_id"] = "different-group"
    with pytest.raises(ValueError, match="subject_identity_mismatch"):
        module.fit_history_models(features, samples)


def test_constant_nonfinite_and_extreme_finite_values_are_auditable():
    module = training()
    features, samples = rows()
    for row in features:
        if row["task_id"] == TASKS[0] and row["evaluation_role"] == "training":
            row["n_pre"] = 2
    fitted = module.fit_history_models(features, samples)
    schedule = model(fitted, TASKS[0], module.history_model_id("ridge", "schedule_history"))
    assert "n_pre" in schedule["constant_columns"]
    assert schedule["scale"][1] == 1.0
    samples[0]["actual"] = math.inf
    failed = module.fit_history_models(features, samples)
    assert model(failed, TASKS[0], module.history_model_id("ridge", "anchor_all"))["reason"] == "nonfinite_training_data"
    assert all("training_targets" not in row for row in failed["models"])
    fitted = module.fit_history_models(*rows())
    probe = deepcopy(rows()[0][0]); probe["anchor_value"] = 1e20
    result = module.predict_history_models([probe], fitted["models"], fitted["estimators"])
    assert prediction(result, probe["sample_id"], module.history_model_id("ridge", "anchor_all"))["status"] == "valid"


def test_insufficient_support_missing_estimator_invalid_model_shape_and_unknown_branch():
    module = training()
    features, samples = rows()
    for row in samples:
        if row["sample_id"].endswith(":b") or row["sample_id"].endswith(":x"):
            row.update(label_status="absent", actual=None)
    failed = module.fit_history_models(features, samples)
    assert len(failed["models"]) == 40
    assert {row["reason"] for row in failed["models"]} == {"insufficient_training_support"}
    fitted = module.fit_history_models(*rows())
    key = f"{TASKS[0]}:{module.history_model_id('ridge', 'anchor_all')}"
    fitted["estimators"].pop(key)
    output = module.predict_history_models(features, fitted["models"], fitted["estimators"])
    assert prediction(output, f"{TASKS[0]}:a", module.history_model_id("ridge", "anchor_all"))["reason"] == "model_missing"
    corrupt = deepcopy(fitted["models"])
    record = model({"models": corrupt}, TASKS[0], module.history_model_id("ridge", "anchor_history"))
    record["mean"].append(0.0)
    output = module.predict_history_models(features, corrupt, fitted["estimators"])
    assert prediction(output, f"{TASKS[0]}:a", record["model_id"])["reason"] == "invalid_model_features"
    with pytest.raises(ValueError, match="unsupported_history_model"):
        module.history_model_id("ridge", "unknown")


def test_fit_exception_and_recorded_failure_replay_do_not_retry(monkeypatch):
    module = training()
    features, samples = rows()
    original, calls = module.Ridge, []

    class FirstFailure(original):
        def fit(self, x, y, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("controlled")
            return super().fit(x, y, **kwargs)

    monkeypatch.setattr(module, "Ridge", FirstFailure)
    key = f"{TASKS[0]}:{module.history_model_id('ridge', 'anchor_all')}"
    first = module.fit_history_models(features, samples)
    assert model(first, TASKS[0], module.history_model_id("ridge", "anchor_all"))["reason"] == "model_fit_error"
    assert len(calls) == 20
    replay = module.fit_history_models(features, samples, recorded_fit_errors=(key,))
    assert len(calls) == 39
    assert replay["models"] == first["models"]


def test_prediction_order_input_immutability_and_all_status_rows():
    module = training()
    features, samples = rows()
    fitted = module.fit_history_models(features, samples)
    supplied = deepcopy(features[::-1]); before = deepcopy(supplied)
    output = module.predict_history_models(supplied, fitted["models"], fitted["estimators"])
    assert supplied == before
    assert len(output) == len(features) * 10
    assert [(row["sample_id"], row["model_id"]) for row in output] == sorted(
        (row["sample_id"], row["model_id"]) for row in output
    )


def test_protocol_parameters_and_prediction_outputs_are_preserved_without_clipping_or_rounding():
    module = training()
    features, samples = rows()
    fitted = module.fit_history_models(features, samples)
    expected = {
        "ridge": {
            "alpha": 1.0, "copy_X": True, "fit_intercept": True,
            "positive": False, "solver": "svd", "tol": 1e-4,
            "max_iter": None, "random_state": None,
        },
        "random_forest": {
            "bootstrap": True, "ccp_alpha": 0.0, "criterion": "squared_error",
            "max_depth": 4, "max_features": 1.0, "max_leaf_nodes": None,
            "max_samples": None, "min_impurity_decrease": 0.0,
            "min_samples_leaf": 3, "min_samples_split": 2,
            "min_weight_fraction_leaf": 0.0, "monotonic_cst": None,
            "n_estimators": 200, "n_jobs": 1, "oob_score": False,
            "random_state": 20260914, "verbose": 0, "warm_start": False,
        },
    }
    for record in fitted["models"]:
        assert record["parameters"] == expected[record["family"]]
        estimator = fitted["estimators"][f'{record["task_id"]}:{record["model_id"]}']
        assert record["parameters"] == estimator.get_params(deep=False)

    probe = deepcopy(features[0])
    probe["anchor_value"] = 1e20
    ridge_id = module.history_model_id("ridge", "anchor_all")
    result = prediction(module.predict_history_models(
        [probe], fitted["models"], fitted["estimators"]
    ), probe["sample_id"], ridge_id)
    assert result["status"] == "valid"
    assert result["value"] == pytest.approx(7.5e19)
    assert result["value"] > 30.0

    class FixedOutput:
        def __init__(self, value):
            self.value = value

        def predict(self, x):
            return [self.value]

    estimator_key = f"{TASKS[0]}:{ridge_id}"
    for output, reason in ((float("nan"), "nonfinite_prediction"),
                           (float("inf"), "nonfinite_prediction")):
        fitted["estimators"][estimator_key] = FixedOutput(output)
        result = prediction(module.predict_history_models(
            [features[0]], fitted["models"], fitted["estimators"]
        ), features[0]["sample_id"], ridge_id)
        assert (result["status"], result["reason"], result["value"]) == ("error", reason, None)

    class RaisingOutput:
        def predict(self, x):
            raise RuntimeError("controlled prediction failure")

    fitted["estimators"][estimator_key] = RaisingOutput()
    result = prediction(module.predict_history_models(
        [features[0]], fitted["models"], fitted["estimators"]
    ), features[0]["sample_id"], ridge_id)
    assert (result["status"], result["reason"], result["value"]) == \
           ("error", "prediction_calculation_error", None)

    fitted["estimators"][estimator_key] = FixedOutput(1.23456789)
    result = prediction(module.predict_history_models(
        [features[0]], fitted["models"], fitted["estimators"]
    ), features[0]["sample_id"], ridge_id)
    assert result["value"] == 1.23456789


def test_absent_training_label_is_excluded_but_input_still_gets_a_prediction():
    module = training()
    features, samples = rows()
    absent_id = f"{TASKS[0]}:x"
    absent = next(row for row in samples if row["sample_id"] == absent_id)
    absent.update(label_status="absent", actual=None)

    fitted = module.fit_history_models(features, samples)
    ridge_id = module.history_model_id("ridge", "anchor_all")
    record = model(fitted, TASKS[0], ridge_id)
    assert absent_id not in record["training_sample_ids"]
    result = prediction(module.predict_history_models(
        features, fitted["models"], fitted["estimators"]
    ), absent_id, ridge_id)
    assert result["status"] == "valid"
    assert result["value"] == pytest.approx(4.0)
    assert math.isfinite(result["value"])


def test_t1_projected_small_synthetic_fixture_end_to_end():
    module = training()
    from app.services.prediction_history_features import project_history_features
    from app.services.synthetic_prediction_cases import build_prediction_inputs
    from app.services.synthetic_prediction_fixtures import build_fixed_fixtures

    fixture = build_fixed_fixtures()[0]
    base = next(row for row in fixture if row["scenario_id"] == "S12" and row["variant"] == "base")
    projected = project_history_features(build_prediction_inputs(base["patients"], base["observations"]))
    assert projected
    # T4 will project the frozen partition metadata; emulate only that explicit boundary here.
    features = [{**row, "pool": "development_pool", "evaluation_role": "training"} for row in projected]
    samples = []
    for index, row in enumerate(features):
        samples.append({key: row[key] for key in (
            "sample_id", "subject_id", "dependency_group_id", "task_id", "horizon_months",
            "anchor_date", "source", "pool", "evaluation_role"
        )} | {"anchor_status": "eligible", "label_status": "valid", "actual": float(index + 1)})
    # The fixed fixture may not have two groups per task; duplicate as a distinct synthetic group.
    extra_features, extra_samples = [], []
    for row, sample in zip(features, samples):
        f, s = deepcopy(row), deepcopy(sample)
        for item in (f, s):
            item["sample_id"] += ":copy"; item["subject_id"] += ":copy"; item["dependency_group_id"] += ":copy"
        extra_features.append(f); extra_samples.append(s)
    fitted = module.fit_history_models(features + extra_features, samples + extra_samples)
    output = module.predict_history_models(projected, fitted["models"], fitted["estimators"])
    assert len(output) == len(projected) * 10
    assert {row["status"] for row in output} == {"valid"}
    assert all(math.isfinite(row["value"]) and row["reason"] is None for row in output)
    for row in projected:
        expected_ids = [row["sample_id"], f'{row["sample_id"]}:copy']
        task_models = [record for record in fitted["models"] if record["task_id"] == row["task_id"]]
        assert len(task_models) == 10
        assert all(record["status"] == "fitted" and record["training_sample_ids"] == expected_ids
                   for record in task_models)
