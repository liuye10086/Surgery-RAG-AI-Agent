"""Fixed offline synthetic candidates and input-only prediction."""

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
    "main_anchor": ("anchor_value",),
    "d03_anchor": ("anchor_value",),
    "d03_augmented": ("anchor_value", "n_pre", "span_pre_days"),
}


def candidate_model_id(family, branch):
    if family not in FAMILIES or branch not in BRANCH_FEATURES:
        raise ValueError("unsupported_candidate")
    return f"{family}:{branch}"


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_sources(features, samples):
    f_index, s_index = {}, {}
    for row, index in ((f, f_index) for f in features):
        key = row["sample_id"]
        if key in index:
            raise ValueError("duplicate_identity")
        index[key] = row
    for row in samples:
        key = row["sample_id"]
        if key in s_index:
            raise ValueError("duplicate_identity")
        s_index[key] = row
    if f_index.keys() != s_index.keys():
        raise ValueError("sample_link_mismatch")
    subject_identity, groups = {}, defaultdict(set)
    subjects_per_task = set()
    for sample_id in sorted(s_index):
        f, s = f_index[sample_id], s_index[sample_id]
        if any(f.get(key) != s.get(key) for key in
               ("subject_id", "dependency_group_id", "task_id", "horizon_months", "anchor_date", "source")):
            raise ValueError("sample_identity_mismatch")
        task, subject, group, pool = (s[key] for key in ("task_id", "subject_id", "dependency_group_id", "pool"))
        if task not in TASKS or pool not in POOLS:
            raise ValueError("unsupported_task_or_pool")
        if "horizon_months" in s and not task.endswith(f'.{s["horizon_months"]}m'):
            raise ValueError("sample_identity_mismatch")
        if (task, subject) in subjects_per_task:
            raise ValueError("duplicate_analysis_patient")
        subjects_per_task.add((task, subject))
        if subject in subject_identity and subject_identity[subject] != (group, pool):
            raise ValueError("subject_partition_mismatch")
        subject_identity[subject] = (group, pool)
        groups[group].add(pool)
        if s["anchor_status"] == "eligible" and f["input_status"] != "available":
            raise ValueError("sample_identity_mismatch")
    if any(len(pools) != 1 for pools in groups.values()):
        raise ValueError("dependency_crosses_pools")
    return f_index, s_index


def _estimator(family):
    if family == "ridge":
        return Ridge(alpha=1.0, fit_intercept=True, solver="svd", positive=False, copy_X=True)
    return RandomForestRegressor(n_estimators=200, criterion="squared_error", max_depth=4,
                                 min_samples_split=2, min_samples_leaf=3, max_features=1.0,
                                 bootstrap=True, oob_score=False, random_state=20260914,
                                 n_jobs=1, warm_start=False)


def fit_candidate_models(features, samples, *, recorded_fit_errors=()):
    """Fit every fixed attempt using only sorted eligible development X and y."""
    try:
        replay_keys = tuple(recorded_fit_errors)
    except TypeError as exc:
        raise ValueError("invalid_recorded_fit_errors") from exc
    supported = {f"{task}:{candidate_model_id(family, branch)}"
                 for task in TASKS for family in FAMILIES for branch in BRANCH_FEATURES}
    if (any(not isinstance(key, str) for key in replay_keys)
            or len(replay_keys) != len(set(replay_keys)) or not set(replay_keys) <= supported):
        raise ValueError("invalid_recorded_fit_errors")
    replay_keys = set(replay_keys)
    f_index, s_index = _validate_sources(features, samples)
    models, estimators = [], {}
    for task in TASKS:
        selected = [s_index[key] for key in sorted(s_index)
                    if s_index[key]["task_id"] == task and s_index[key]["pool"] == "development_pool"
                    and s_index[key]["anchor_status"] == "eligible" and s_index[key]["label_status"] == "valid"]
        for family in FAMILIES:
            for branch, names in BRANCH_FEATURES.items():
                train = selected if branch == "main_anchor" else [s for s in selected
                    if f_index[s["sample_id"]].get("n_pre") is not None
                    and f_index[s["sample_id"]].get("span_pre_days") is not None]
                identity = [{key: s[key] for key in ("sample_id", "subject_id", "dependency_group_id")}
                            for s in train]
                estimator = _estimator(family)
                record = {"task_id": task, "model_id": candidate_model_id(family, branch),
                          "family": family, "branch": branch, "status": "error", "reason": None,
                          "feature_names": list(names), "training_sample_ids": [s["sample_id"] for s in train],
                          "training_subject_ids": [s["subject_id"] for s in train],
                          "training_dependency_groups": sorted({s["dependency_group_id"] for s in train}),
                          "training_identity_sha256": _hash(identity), "training_data_sha256": None,
                          "mean": None, "std": None, "scale": None, "constant_columns": [],
                          "parameters": estimator.get_params(deep=False)}
                if family == "ridge":
                    record.update(coef=None, intercept=None)
                x = [[f_index[s["sample_id"]].get(name) for name in names] for s in train]
                y = [s["actual"] for s in train]
                valid_data = all(_finite(value) for row in x for value in row) and all(_finite(value) for value in y)
                if valid_data:
                    record["training_data_sha256"] = _hash({"identity": identity, "feature_names": list(names), "X": x, "y": y})
                if len({s["dependency_group_id"] for s in train}) < 2:
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
                record.update(mean=mean.tolist(), std=std.tolist(), scale=scale.tolist(),
                              constant_columns=[name for name, sigma in zip(names, std) if sigma == 0])
                if f'{task}:{record["model_id"]}' in replay_keys:
                    record["reason"] = "model_fit_error"
                    models.append(record)
                    continue
                try:
                    estimator.fit((matrix - mean) / scale, np.asarray(y, dtype=float))
                    if family == "ridge":
                        coef = np.asarray(estimator.coef_, dtype=float).reshape(-1)
                        intercept = float(estimator.intercept_)
                        if not np.isfinite(coef).all() or not math.isfinite(intercept):
                            raise ArithmeticError("nonfinite_model_parameters")
                        record.update(coef=coef.tolist(), intercept=intercept)
                    if not np.isfinite(estimator.predict((matrix - mean) / scale)).all():
                        raise ArithmeticError("nonfinite_model_parameters")
                except (ArithmeticError, ValueError, TypeError, RuntimeError, FloatingPointError):
                    record["reason"] = "model_fit_error"
                    if family == "ridge":
                        record.update(coef=None, intercept=None)
                else:
                    record.update(status="fitted", reason=None)
                    estimators[f'{task}:{record["model_id"]}'] = estimator
                models.append(record)
    return {"models": models, "estimators": estimators}


def predict_candidate_models(features, models, estimators):
    """Predict from input projections; outcome samples are deliberately not accepted."""
    by_key = {}
    for record in models:
        key = (record["task_id"], record["model_id"])
        if key in by_key:
            raise ValueError("duplicate_model_identity")
        by_key[key] = record
    seen, predictions = set(), []
    for f in sorted(features, key=lambda row: row["sample_id"]):
        if f["sample_id"] in seen:
            raise ValueError("duplicate_identity")
        seen.add(f["sample_id"])
        task = f["task_id"]
        if task not in TASKS:
            raise ValueError("unsupported_task")
        for family in FAMILIES:
            for branch, names in BRANCH_FEATURES.items():
                model_id = candidate_model_id(family, branch)
                record = by_key.get((task, model_id))
                status, reason, value = "valid", None, None
                if f["input_status"] != "available":
                    status, reason = "abstain", "anchor_not_available"
                elif branch != "main_anchor" and (f.get("n_pre") is None or f.get("span_pre_days") is None):
                    status, reason = "abstain", "d03_history_unknown"
                elif not all(_finite(f.get(name)) for name in names):
                    status, reason = "error", "nonfinite_prediction_input"
                elif record is None:
                    status, reason = "error", "model_missing"
                elif record["status"] != "fitted":
                    status, reason = "error", record["reason"] or "model_fit_error"
                elif record["feature_names"] != list(names):
                    status, reason = "error", "invalid_model_features"
                else:
                    estimator = estimators.get(f"{task}:{model_id}")
                    if estimator is None:
                        status, reason = "error", "model_missing"
                    elif not all(_finite(number) for number in record["mean"] + record["scale"]):
                        status, reason = "error", "nonfinite_model_parameters"
                    else:
                        try:
                            scaled = [(f[name] - mu) / sigma for name, mu, sigma in
                                      zip(names, record["mean"], record["scale"])]
                            value = float(estimator.predict(np.asarray([scaled], dtype=float))[0])
                            if not math.isfinite(value):
                                status, reason, value = "error", "nonfinite_prediction", None
                        except (ArithmeticError, ValueError, TypeError, RuntimeError, OverflowError):
                            status, reason, value = "error", "prediction_calculation_error", None
                predictions.append({"sample_id": f["sample_id"], "task_id": task, "model_id": model_id,
                                    "status": status, "value": value, "reason": reason})
    return predictions
