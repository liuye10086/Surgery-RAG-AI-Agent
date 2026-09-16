"""Fixed history-feature models for the offline synthetic experiment."""

from collections import defaultdict
import hashlib
import math

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge

from app.services.prediction_calculation import POOLS, TASKS
from app.services.synthetic_prediction_cases import canonical_json


FAMILIES = ("ridge", "random_forest")
BRANCH_FEATURES = {
    "anchor_all": ("anchor_value",),
    "anchor_history": ("anchor_value",),
    "schedule_history": ("anchor_value", "n_pre", "span_pre_days"),
    "value_history": ("anchor_value", "prior_value", "slope_per_day"),
    "value_schedule_history": (
        "anchor_value", "prior_value", "slope_per_day", "n_pre", "span_pre_days"
    ),
}
HISTORY_BRANCHES = tuple(branch for branch in BRANCH_FEATURES if branch != "anchor_all")
ROLE_POOLS = {
    "training": "development_pool",
    "internal_validation": "development_pool",
    "challenge": "challenge_pool",
}
MODEL_VERSION = "history_v1"


def history_model_id(family, branch):
    if family not in FAMILIES or branch not in BRANCH_FEATURES:
        raise ValueError("unsupported_history_model")
    return f"{family}:{MODEL_VERSION}:{branch}"


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _estimator(family):
    if family == "ridge":
        return Ridge(alpha=1.0, fit_intercept=True, solver="svd", positive=False, copy_X=True)
    return RandomForestRegressor(
        n_estimators=200, criterion="squared_error", max_depth=4,
        min_samples_split=2, min_samples_leaf=3, max_features=1.0,
        bootstrap=True, oob_score=False, random_state=20260914,
        n_jobs=1, warm_start=False,
    )


def _validate_sources(features, training_samples):
    feature_index = {}
    sample_index = {}
    task_subjects = set()
    subject_partitions = {}
    group_partitions = defaultdict(set)

    for row in features:
        sample_id = row["sample_id"]
        if sample_id in feature_index:
            raise ValueError("duplicate_identity")
        feature_index[sample_id] = row
        task = row["task_id"]
        pool = row.get("pool")
        role = row.get("evaluation_role")
        if task not in TASKS or pool not in POOLS or ROLE_POOLS.get(role) != pool:
            raise ValueError("unsupported_task_or_partition")
        if row.get("history_status") not in {"available", "abstain", "error"}:
            raise ValueError("invalid_history_status")
        if "horizon_months" in row and not task.endswith(f'.{row["horizon_months"]}m'):
            raise ValueError("sample_identity_mismatch")
        task_subject = (task, row["subject_id"])
        if task_subject in task_subjects:
            raise ValueError("duplicate_analysis_patient")
        task_subjects.add(task_subject)
        partition = (pool, role)
        subject = row["subject_id"]
        subject_identity = (row["dependency_group_id"], pool, role)
        if subject in subject_partitions and subject_partitions[subject] != subject_identity:
            raise ValueError("subject_identity_mismatch")
        subject_partitions[subject] = subject_identity
        group_partitions[row["dependency_group_id"]].add(partition)

    if any(len(partitions) != 1 for partitions in group_partitions.values()):
        raise ValueError("dependency_crosses_partitions")

    identity_keys = (
        "subject_id", "dependency_group_id", "task_id", "horizon_months",
        "anchor_date", "source", "pool", "evaluation_role",
    )
    for row in training_samples:
        sample_id = row["sample_id"]
        if sample_id in sample_index:
            raise ValueError("duplicate_identity")
        if row.get("pool") != "development_pool" or row.get("evaluation_role") != "training":
            raise ValueError("training_role_required")
        feature = feature_index.get(sample_id)
        if feature is None:
            raise ValueError("sample_link_mismatch")
        if any(feature.get(key) != row.get(key) for key in identity_keys):
            if (feature.get("pool"), feature.get("evaluation_role")) != \
                    (row.get("pool"), row.get("evaluation_role")):
                raise ValueError("sample_role_mismatch")
            raise ValueError("sample_identity_mismatch")
        if row.get("anchor_status") == "eligible" and feature.get("input_status") != "available":
            raise ValueError("sample_identity_mismatch")
        sample_index[sample_id] = row
    expected_training_ids = {
        sample_id for sample_id, row in feature_index.items()
        if row["pool"] == "development_pool" and row["evaluation_role"] == "training"
    }
    if set(sample_index) != expected_training_ids:
        raise ValueError("training_sample_set_mismatch")
    return feature_index, sample_index


def _validate_replay_keys(recorded_fit_errors):
    try:
        keys = tuple(recorded_fit_errors)
    except TypeError as exc:
        raise ValueError("invalid_recorded_fit_errors") from exc
    supported = {
        f"{task}:{history_model_id(family, branch)}"
        for task in TASKS for family in FAMILIES for branch in BRANCH_FEATURES
    }
    if (any(not isinstance(key, str) for key in keys)
            or len(keys) != len(set(keys)) or not set(keys) <= supported):
        raise ValueError("invalid_recorded_fit_errors")
    return set(keys)


def fit_history_models(features: list[dict], training_samples: list[dict], *,
                       recorded_fit_errors: tuple[str, ...] = ()) -> dict:
    """Fit all fixed attempts from explicitly identified training-role outcomes."""
    replay_keys = _validate_replay_keys(recorded_fit_errors)
    feature_index, sample_index = _validate_sources(features, training_samples)
    models, estimators = [], {}

    for task in TASKS:
        eligible = [sample_index[sample_id] for sample_id in sorted(sample_index)
                    if sample_index[sample_id]["task_id"] == task
                    and sample_index[sample_id].get("anchor_status") == "eligible"
                    and sample_index[sample_id].get("label_status") == "valid"]
        history = [sample for sample in eligible
                   if feature_index[sample["sample_id"]].get("history_status") in {"available", "error"}]
        for family in FAMILIES:
            for branch, names in BRANCH_FEATURES.items():
                train = eligible if branch == "anchor_all" else history
                identity = [{key: sample[key]
                             for key in ("sample_id", "subject_id", "dependency_group_id")}
                            for sample in train]
                estimator = _estimator(family)
                model_id = history_model_id(family, branch)
                record = {
                    "task_id": task, "model_id": model_id, "family": family,
                    "branch": branch, "status": "error", "reason": None,
                    "feature_names": list(names),
                    "training_sample_ids": [sample["sample_id"] for sample in train],
                    "training_subject_ids": [sample["subject_id"] for sample in train],
                    "training_dependency_groups": sorted(
                        {sample["dependency_group_id"] for sample in train}
                    ),
                    "training_identity_sha256": _hash(identity),
                    "training_target_sha256": None,
                    "training_data_sha256": None,
                    "mean": None, "std": None, "scale": None,
                    "constant_columns": [], "parameters": estimator.get_params(deep=False),
                }
                if family == "ridge":
                    record.update(coef=None, intercept=None)
                x = [[feature_index[sample["sample_id"]].get(name) for name in names]
                     for sample in train]
                y = [sample.get("actual") for sample in train]
                valid_data = (all(_finite(value) for row in x for value in row)
                              and all(_finite(value) for value in y))
                if all(_finite(value) for value in y):
                    record["training_target_sha256"] = _hash(y)
                if valid_data:
                    record["training_data_sha256"] = _hash({
                        "identity": identity, "feature_names": list(names), "X": x, "y": y,
                    })
                if len({sample["dependency_group_id"] for sample in train}) < 2:
                    record["reason"] = "insufficient_training_support"
                    models.append(record)
                    continue
                if not valid_data:
                    record["reason"] = "nonfinite_training_data"
                    models.append(record)
                    continue
                matrix = np.asarray(x, dtype=float)
                mean = matrix.mean(axis=0)
                std = matrix.std(axis=0, ddof=0)
                scale = np.where(std == 0, 1.0, std)
                if not np.isfinite(mean).all() or not np.isfinite(scale).all():
                    record["reason"] = "nonfinite_training_data"
                    models.append(record)
                    continue
                record.update(
                    mean=mean.tolist(), std=std.tolist(), scale=scale.tolist(),
                    constant_columns=[name for name, sigma in zip(names, std) if sigma == 0],
                )
                attempt_key = f"{task}:{model_id}"
                if attempt_key in replay_keys:
                    record["reason"] = "model_fit_error"
                    models.append(record)
                    continue
                try:
                    scaled = (matrix - mean) / scale
                    estimator.fit(scaled, np.asarray(y, dtype=float))
                    if family == "ridge":
                        coef = np.asarray(estimator.coef_, dtype=float).reshape(-1)
                        intercept = float(estimator.intercept_)
                        if len(coef) != len(names) or not np.isfinite(coef).all() or not math.isfinite(intercept):
                            raise ArithmeticError("nonfinite_model_parameters")
                        record.update(coef=coef.tolist(), intercept=intercept)
                    fitted_values = np.asarray(estimator.predict(scaled), dtype=float).reshape(-1)
                    if len(fitted_values) != len(train) or not np.isfinite(fitted_values).all():
                        raise ArithmeticError("nonfinite_model_parameters")
                except (ArithmeticError, ValueError, TypeError, RuntimeError, FloatingPointError, OverflowError):
                    record["reason"] = "model_fit_error"
                    if family == "ridge":
                        record.update(coef=None, intercept=None)
                else:
                    record.update(status="fitted", reason=None)
                    estimators[attempt_key] = estimator
                models.append(record)
    return {"models": models, "estimators": estimators}


def _model_index(models):
    index = {}
    for record in models:
        task = record.get("task_id")
        family = record.get("family")
        branch = record.get("branch")
        if task not in TASKS:
            raise ValueError("unsupported_task")
        expected = history_model_id(family, branch)
        if record.get("model_id") != expected:
            raise ValueError("unsupported_history_model")
        key = (task, expected)
        if key in index:
            raise ValueError("duplicate_model_identity")
        index[key] = record
    return index


def predict_history_models(features: list[dict], models: list[dict], estimators: dict) -> list[dict]:
    """Predict every fixed branch from input features without accepting outcomes."""
    model_index = _model_index(models)
    seen, predictions = set(), []
    for feature in sorted(features, key=lambda row: row["sample_id"]):
        sample_id = feature["sample_id"]
        if sample_id in seen:
            raise ValueError("duplicate_identity")
        seen.add(sample_id)
        task = feature["task_id"]
        if task not in TASKS:
            raise ValueError("unsupported_task")
        if feature.get("history_status") not in {"available", "abstain", "error"}:
            raise ValueError("invalid_history_status")
        for family in FAMILIES:
            for branch, names in BRANCH_FEATURES.items():
                model_id = history_model_id(family, branch)
                record = model_index.get((task, model_id))
                status, reason, value = "valid", None, None
                if feature.get("input_status") != "available":
                    status, reason = "abstain", "anchor_not_available"
                elif branch != "anchor_all" and feature.get("history_status") == "abstain":
                    status, reason = "abstain", feature.get("history_reason") or "history_unavailable"
                elif (branch in {"value_history", "value_schedule_history"}
                      and feature.get("history_status") == "error"):
                    status, reason = "error", feature.get("history_reason") or "history_calculation_error"
                elif not all(_finite(feature.get(name)) for name in names):
                    status, reason = "error", "nonfinite_prediction_input"
                elif record is None:
                    status, reason = "error", "model_missing"
                elif record.get("status") != "fitted":
                    status, reason = "error", record.get("reason") or "model_fit_error"
                elif record.get("feature_names") != list(names):
                    status, reason = "error", "invalid_model_features"
                else:
                    mean, scale = record.get("mean"), record.get("scale")
                    if (not isinstance(mean, list) or not isinstance(scale, list)
                            or len(mean) != len(names) or len(scale) != len(names)
                            or not all(_finite(number) for number in mean + scale)
                            or any(number <= 0 for number in scale)):
                        status, reason = "error", "invalid_model_features"
                    else:
                        estimator = estimators.get(f"{task}:{model_id}")
                        if estimator is None:
                            status, reason = "error", "model_missing"
                        else:
                            try:
                                scaled = [(feature[name] - mean[index]) / scale[index]
                                          for index, name in enumerate(names)]
                                output = np.asarray(
                                    estimator.predict(np.asarray([scaled], dtype=float)), dtype=float
                                ).reshape(-1)
                                if len(output) != 1:
                                    raise ValueError("invalid_prediction_shape")
                                value = float(output[0])
                                if not math.isfinite(value):
                                    status, reason, value = "error", "nonfinite_prediction", None
                            except (ArithmeticError, ValueError, TypeError, RuntimeError,
                                    FloatingPointError, OverflowError, KeyError, IndexError):
                                status, reason, value = "error", "prediction_calculation_error", None
                predictions.append({
                    "sample_id": sample_id, "task_id": task, "model_id": model_id,
                    "status": status, "value": value, "reason": reason,
                })
    return sorted(predictions, key=lambda row: (row["sample_id"], row["model_id"]))
