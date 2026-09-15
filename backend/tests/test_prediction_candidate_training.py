"""Contract tests for isolated synthetic candidate fitting and inference."""

from copy import deepcopy

import pytest

from app.services import prediction_candidate_training as training
from app.services.prediction_calculation import TASKS


def rows():
    features, samples = [], []
    for task in TASKS:
        for suffix, pool, value, actual, n_pre, span in (
            ("a", "development_pool", 0, 1, 0, 0),
            ("b", "development_pool", 2, 3, 2, 42),
            ("c", "challenge_pool", 3, 99, 1, 12),
            ("u", "challenge_pool", 4, 88, None, None),
        ):
            identity = {"sample_id": f"{task}:{suffix}", "task_id": task,
                        "subject_id": f"{task}:{suffix}", "dependency_group_id": f"{task}:{suffix}",
                        "horizon_months": 6 if task.endswith(".6m") else 12,
                        "anchor_date": "2024-01-01", "source": "synthetic"}
            features.append({**identity, "input_status": "available", "anchor_value": value,
                             "n_pre": n_pre, "span_pre_days": span})
            samples.append({**identity, "pool": pool, "anchor_status": "eligible",
                            "label_status": "valid", "actual": actual})
    return features, samples


def model(result, task, model_id):
    return next(record for record in result["models"] if record["task_id"] == task and record["model_id"] == model_id)


def prediction(predictions, sample_id, model_id):
    return next(p for p in predictions if p["sample_id"] == sample_id and p["model_id"] == model_id)


def test_literal_ridge_and_d03_identical_training_identity():
    features, samples = rows()
    fitted = training.fit_candidate_models(features, samples)
    task = TASKS[0]
    ridge = model(fitted, task, "ridge:main_anchor")
    anchor = model(fitted, task, "ridge:d03_anchor")
    augmented = model(fitted, task, "ridge:d03_augmented")
    assert len(fitted["models"]) == 24
    assert len(fitted["estimators"]) == 24
    assert ridge["status"] == "fitted"
    assert ridge["reason"] is None
    assert ridge["feature_names"] == ["anchor_value"]
    assert ridge["training_sample_ids"] == [f"{task}:a", f"{task}:b"]
    assert ridge["mean"] == [1.0]
    assert ridge["std"] == [1.0]
    assert ridge["scale"] == [1.0]
    assert ridge["coef"][0] == pytest.approx(2 / 3)
    assert ridge["intercept"] == pytest.approx(2)
    assert anchor["training_sample_ids"] == augmented["training_sample_ids"]
    assert anchor["training_dependency_groups"] == augmented["training_dependency_groups"]
    assert anchor["training_identity_sha256"] == augmented["training_identity_sha256"]
    assert anchor["training_data_sha256"] != augmented["training_data_sha256"]
    assert augmented["feature_names"] == ["anchor_value", "n_pre", "span_pre_days"]
    assert "alpha" in ridge["parameters"]
    assert "n_estimators" in model(fitted, task, "random_forest:main_anchor")["parameters"]
    predictions = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(predictions, f"{task}:c", "ridge:main_anchor")["value"] == pytest.approx(10 / 3)
    assert prediction(predictions, f"{task}:u", "ridge:d03_augmented")["status"] == "abstain"
    assert prediction(predictions, f"{task}:a", "ridge:d03_augmented")["status"] == "valid"


def test_development_only_and_row_order_determinism():
    features, samples = rows()
    baseline = training.fit_candidate_models(features, samples)
    modified_features, modified_samples = deepcopy(features), deepcopy(samples)
    for f, s in zip(modified_features, modified_samples):
        if s["pool"] == "challenge_pool":
            f["anchor_value"] += 300
            s["actual"] = -9
    changed = training.fit_candidate_models(modified_features, modified_samples)
    assert changed["models"] == baseline["models"]
    reverse = training.fit_candidate_models(features[::-1], samples[::-1])
    assert reverse["models"] == baseline["models"]
    before = training.predict_candidate_models(features, baseline["models"], baseline["estimators"])
    after = training.predict_candidate_models(features, changed["models"], changed["estimators"])
    assert after == before
    assert training.predict_candidate_models(features[::-1], reverse["models"], reverse["estimators"]) == before
    modified_samples[0]["actual"] = 9
    relabeled = training.fit_candidate_models(features, modified_samples)
    assert model(relabeled, TASKS[0], "ridge:main_anchor")["mean"] == [1.0]
    assert model(relabeled, TASKS[0], "ridge:main_anchor")["coef"] != model(baseline, TASKS[0], "ridge:main_anchor")["coef"]


def test_constant_column_uses_unit_scale():
    features, samples = rows()
    for f in features:
        if f["task_id"] == TASKS[0] and f["sample_id"].endswith(":b"):
            f["anchor_value"] = 0
    fitted = training.fit_candidate_models(features, samples)
    ridge = model(fitted, TASKS[0], "ridge:main_anchor")
    assert ridge["std"] == [0.0]
    assert ridge["scale"] == [1.0]
    assert ridge["constant_columns"] == ["anchor_value"]
    assert prediction(training.predict_candidate_models(features, fitted["models"], fitted["estimators"]),
                      f"{TASKS[0]}:c", "ridge:main_anchor")["status"] == "valid"


def test_unknown_history_development_patient_trains_main_but_neither_d03_branch():
    features, samples = rows()
    extra_feature, extra_sample = deepcopy(features[0]), deepcopy(samples[0])
    extra_id = f"{TASKS[0]}:unknown_development"
    for row in (extra_feature, extra_sample):
        row.update(sample_id=extra_id, subject_id=extra_id, dependency_group_id=extra_id)
    extra_feature.update(anchor_value=100, n_pre=None, span_pre_days=None)
    extra_sample["actual"] = 1000
    features.append(extra_feature)
    samples.append(extra_sample)

    fitted = training.fit_candidate_models(features, samples)
    predictions = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    for family in training.FAMILIES:
        main = model(fitted, TASKS[0], f"{family}:main_anchor")
        anchor = model(fitted, TASKS[0], f"{family}:d03_anchor")
        augmented = model(fitted, TASKS[0], f"{family}:d03_augmented")
        assert extra_id in main["training_sample_ids"]
        assert extra_id not in anchor["training_sample_ids"]
        assert anchor["training_sample_ids"] == augmented["training_sample_ids"]
        assert anchor["training_identity_sha256"] == augmented["training_identity_sha256"]
        assert main["mean"] == [34.0]
        assert anchor["mean"] == [1.0]
        assert augmented["mean"][0] == 1.0
        assert prediction(predictions, extra_id, f"{family}:main_anchor")["status"] == "valid"
        assert prediction(predictions, extra_id, f"{family}:d03_anchor")["status"] == "abstain"
        assert prediction(predictions, extra_id, f"{family}:d03_augmented")["status"] == "abstain"


def test_extreme_finite_output_is_retained_without_clipping():
    features, samples = rows()
    fitted = training.fit_candidate_models(features, samples)

    class ExtremeOutput:
        def predict(self, x):
            return [-1e100]

    fitted["estimators"][f"{TASKS[0]}:ridge:main_anchor"] = ExtremeOutput()
    predictions = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    result = prediction(predictions, f"{TASKS[0]}:c", "ridge:main_anchor")
    assert result == {"sample_id": f"{TASKS[0]}:c", "task_id": TASKS[0],
                      "model_id": "ridge:main_anchor", "status": "valid", "value": -1e100,
                      "reason": None}


@pytest.mark.parametrize("change, reason", [
    (lambda f, s: (f[1].update(subject_id=s[0]["subject_id"]), s[1].update(subject_id=s[0]["subject_id"])), "duplicate_analysis_patient"),
    (lambda f, s: (f[2].update(dependency_group_id=s[0]["dependency_group_id"]), s[2].update(dependency_group_id=s[0]["dependency_group_id"])), "dependency_crosses_pools"),
    (lambda f, s: f[0].update(subject_id="wrong"), "sample_identity_mismatch"),
    (lambda f, s: f[0].update(anchor_date="2024-02-01"), "sample_identity_mismatch"),
    (lambda f, s: s[0].update(task_id=TASKS[1]), "sample_identity_mismatch"),
])
def test_invalid_partition_or_identity_is_rejected(change, reason):
    features, samples = rows()
    change(features, samples)
    with pytest.raises(ValueError, match=reason):
        training.fit_candidate_models(features, samples)


def test_insufficient_support_preserves_all_attempts_and_missing_model_errors():
    features, samples = rows()
    for s in samples:
        if s["pool"] == "development_pool" and s["sample_id"].endswith(":b"):
            s["label_status"], s["actual"] = "absent", None
    fitted = training.fit_candidate_models(features, samples)
    assert len(fitted["models"]) == 24
    assert not fitted["estimators"]
    assert {m["reason"] for m in fitted["models"]} == {"insufficient_training_support"}
    predictions = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(predictions, f"{TASKS[0]}:c", "ridge:main_anchor")["reason"] == "insufficient_training_support"
    assert prediction(predictions, f"{TASKS[0]}:u", "ridge:d03_anchor")["reason"] == "d03_history_unknown"
    fitted = training.fit_candidate_models(*rows())
    fitted["estimators"].pop(f'{TASKS[0]}:ridge:main_anchor')
    p = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(p, f"{TASKS[0]}:c", "ridge:main_anchor")["reason"] == "model_missing"


def test_nonfinite_training_and_prediction_are_recorded_as_errors():
    features, samples = rows()
    samples[0]["actual"] = float("nan")
    fitted = training.fit_candidate_models(features, samples)
    assert model(fitted, TASKS[0], "ridge:main_anchor")["reason"] == "nonfinite_training_data"
    assert model(fitted, TASKS[0], "ridge:d03_augmented")["reason"] == "nonfinite_training_data"
    features, samples = rows()
    fitted = training.fit_candidate_models(features, samples)
    features[2]["anchor_value"] = float("inf")
    p = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(p, f"{TASKS[0]}:c", "ridge:main_anchor")["reason"] == "nonfinite_prediction_input"


def test_unavailable_anchor_and_unknown_history_abstain_even_without_label():
    features, samples = rows()
    samples[2]["label_status"], samples[2]["actual"] = "pending", None
    fitted = training.fit_candidate_models(features, samples)
    p = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(p, f"{TASKS[0]}:c", "ridge:main_anchor")["status"] == "valid"
    features[2]["input_status"] = "unavailable"
    p = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(p, f"{TASKS[0]}:c", "ridge:main_anchor")["status"] == "abstain"
    assert prediction(p, f"{TASKS[0]}:u", "ridge:d03_anchor")["status"] == "abstain"


def test_fit_exception_and_nonfinite_output_are_observable(monkeypatch):
    features, samples = rows()
    original = training.Ridge

    class BrokenRidge(original):
        def fit(self, x, y, **kwargs):
            raise RuntimeError("controlled synthetic failure")

    monkeypatch.setattr(training, "Ridge", BrokenRidge)
    failed = training.fit_candidate_models(features, samples)
    assert model(failed, TASKS[0], "ridge:main_anchor")["reason"] == "model_fit_error"
    assert f"{TASKS[0]}:ridge:main_anchor" not in failed["estimators"]
    assert model(failed, TASKS[0], "random_forest:main_anchor")["status"] == "fitted"
    monkeypatch.setattr(training, "Ridge", original)
    fitted = training.fit_candidate_models(features, samples)

    class InvalidOutput:
        def predict(self, x):
            return [float("inf")]

    fitted["estimators"][f"{TASKS[0]}:ridge:main_anchor"] = InvalidOutput()
    p = training.predict_candidate_models(features, fitted["models"], fitted["estimators"])
    assert prediction(p, f"{TASKS[0]}:c", "ridge:main_anchor")["reason"] == "nonfinite_prediction"
    assert prediction(p, f"{TASKS[0]}:c", "random_forest:main_anchor")["status"] == "valid"


def test_training_identity_hash_is_present_without_enough_support():
    features, samples = rows()
    for s in samples:
        if s["pool"] == "development_pool" and s["sample_id"].endswith(":b"):
            s["label_status"], s["actual"] = "absent", None
    fitted = training.fit_candidate_models(features, samples)
    record = model(fitted, TASKS[0], "ridge:main_anchor")
    assert record["status"] == "error"
    assert record["training_data_sha256"] is not None


def test_candidate_model_id_rejects_unknown_family_or_branch():
    assert training.candidate_model_id("ridge", "d03_anchor") == "ridge:d03_anchor"
    with pytest.raises(ValueError, match="unsupported_candidate"):
        training.candidate_model_id("extra", "d03_anchor")
    with pytest.raises(ValueError, match="unsupported_candidate"):
        training.candidate_model_id("ridge", "unknown")


def test_task_id_must_match_declared_horizon_even_when_both_inputs_are_relabelled():
    features, samples = rows()
    features[0]["task_id"] = TASKS[1]
    samples[0]["task_id"] = TASKS[1]
    with pytest.raises(ValueError, match="sample_identity_mismatch"):
        training.fit_candidate_models(features, samples)


def test_recorded_fit_error_replays_without_refitting_that_attempt(monkeypatch):
    features, samples = rows()
    original = training.Ridge
    calls = []

    class FirstOnlyFailure(original):
        def fit(self, x, y, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("first attempt failed")
            return super().fit(x, y, **kwargs)

    monkeypatch.setattr(training, "Ridge", FirstOnlyFailure)
    key = f"{TASKS[0]}:ridge:main_anchor"
    first = training.fit_candidate_models(features, samples)
    failed = model(first, TASKS[0], "ridge:main_anchor")
    assert failed["status"] == "error"
    assert failed["reason"] == "model_fit_error"
    assert len(first["estimators"]) == 23
    assert len(calls) == 12

    replay = training.fit_candidate_models(features, samples, recorded_fit_errors=[key])
    assert len(calls) == 23
    assert len(replay["estimators"]) == 23
    assert replay["models"] == first["models"]
    assert training.predict_candidate_models(features, replay["models"], replay["estimators"]) == \
        training.predict_candidate_models(features, first["models"], first["estimators"])


@pytest.mark.parametrize("keys", [
    ["unknown:ridge:main_anchor"],
    [f"{TASKS[0]}:ridge:unknown"],
    [f"{TASKS[0]}:ridge:main_anchor", f"{TASKS[0]}:ridge:main_anchor"],
])
def test_recorded_fit_error_keys_must_be_unique_and_supported(keys):
    features, samples = rows()
    with pytest.raises(ValueError, match="invalid_recorded_fit_errors"):
        training.fit_candidate_models(features, samples, recorded_fit_errors=keys)


def test_fit_error_clears_partial_ridge_learned_parameters(monkeypatch):
    features, samples = rows()
    original = training.Ridge

    class PredictFailure(original):
        def predict(self, x):
            raise RuntimeError("post-fit prediction failed")

    monkeypatch.setattr(training, "Ridge", PredictFailure)
    failed = training.fit_candidate_models(features, samples)
    ridge = model(failed, TASKS[0], "ridge:main_anchor")
    assert ridge["reason"] == "model_fit_error"
    assert ridge["coef"] is None
    assert ridge["intercept"] is None
    assert ridge["mean"] == [1.0]
    assert ridge["training_data_sha256"] is not None
