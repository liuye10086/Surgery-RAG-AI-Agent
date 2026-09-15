"""Patient-weighted paired errors and dependency-group bootstrap intervals."""

import math
from collections import Counter
from numbers import Real

import numpy as np


_METRICS = ("mae", "rmse", "bias", "baseline_mae", "mae_gain")


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value)


def _validated_rows(rows):
    rows = list(rows)
    subjects = [row["subject_id"] for row in rows]
    if len(subjects) != len(set(subjects)):
        raise ValueError("duplicate subject_id")
    return rows


def paired_statistics(rows, weights=None):
    """Calculate paired patient-weighted point estimates without coercing evidence."""
    rows = _validated_rows(rows)
    if weights is None:
        weights = [1] * len(rows)
    else:
        weights = list(weights)
        if len(weights) != len(rows) or any(not _finite(w) or w < 0 for w in weights):
            raise ValueError("invalid patient weights")
        try:
            weight_sum = math.fsum(weights)
        except OverflowError as exc:
            raise ValueError("patient weights must have positive finite sum") from exc
        if not weights or not math.isfinite(weight_sum) or weight_sum <= 0:
            raise ValueError("patient weights must have positive finite sum")
    result = {key: None for key in (*_METRICS, "alpha", "beta")}
    result.update(n_patients=len(rows), n_groups=len({r["dependency_group_id"] for r in rows}), unavailable=[])
    if not rows:
        result["unavailable"].append("empty_rows")
        return result
    ordered = sorted(zip(rows, weights), key=lambda item: (str(item[0]["dependency_group_id"]), str(item[0]["subject_id"])))
    active = [(r, w) for r, w in ordered if w > 0]
    try:
        total = math.fsum(w for _, w in active)
    except OverflowError:
        total = float("inf")
    if not active or not math.isfinite(total):
        result["unavailable"].append("invalid_weight_sum")
        return result

    def weighted(values):
        try:
            value = math.fsum(w * v for (_, w), v in zip(active, values)) / total
        except (OverflowError, ValueError, ZeroDivisionError):
            return None
        return value if math.isfinite(value) else None

    actual_ok = all(_finite(r["actual"]) for r, _ in active)
    prediction_ok = all(_finite(r["prediction"]) for r, _ in active)
    baseline_ok = all(_finite(r["baseline"]) for r, _ in active)
    if actual_ok and baseline_ok:
        result["baseline_mae"] = weighted([abs(r["baseline"] - r["actual"]) for r, _ in active])
    if actual_ok and prediction_ok:
        errors = [r["prediction"] - r["actual"] for r, _ in active]
        result["mae"] = weighted([abs(e) for e in errors])
        squared = weighted([e * e for e in errors])
        result["rmse"] = math.sqrt(squared) if squared is not None else None
        result["bias"] = weighted(errors)
        predictions = [r["prediction"] for r, _ in active]
        mean_p = weighted(predictions)
        mean_y = weighted([r["actual"] for r, _ in active])
        if mean_p is not None and mean_y is not None:
            try:
                variance_terms = [(p - mean_p) ** 2 for p in predictions]
                covariance_terms = [(p - mean_p) * (r["actual"] - mean_y)
                                    for (r, _), p in zip(active, predictions)]
            except OverflowError:
                variance_terms, covariance_terms = [], []
            variance = weighted(variance_terms) if variance_terms else None
            covariance = weighted(covariance_terms) if covariance_terms else None
            if variance is not None and variance > 0 and covariance is not None:
                beta = covariance / variance
                alpha = mean_y - beta * mean_p
                if math.isfinite(alpha) and math.isfinite(beta):
                    result["alpha"], result["beta"] = alpha, beta
    if actual_ok and prediction_ok and baseline_ok:
        paired_gains = [abs(r["baseline"] - r["actual"]) -
                        abs(r["prediction"] - r["actual"]) for r, _ in active]
        result["mae_gain"] = weighted(paired_gains)
    result["unavailable"] = [f"{key}:invalid_or_insufficient_numeric_evidence"
                             for key in (*_METRICS, "alpha", "beta") if result[key] is None]
    return result


def paired_bootstrap(rows, *, seed=20260910, iterations=2000, draw_indices=None):
    """Resample groups, applying each group's multiplicity to all paired patients."""
    rows = _validated_rows(rows)
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations <= 0:
        raise ValueError("iterations must be a positive integer")
    groups = sorted({r["dependency_group_id"] for r in rows}, key=lambda group: str(group))
    group_count = len(groups)
    if draw_indices is not None:
        draw_indices = list(draw_indices)
        if len(draw_indices) != iterations:
            raise ValueError("draw count must equal iterations")
        for draw in draw_indices:
            if len(draw) != group_count or any(isinstance(i, (bool, np.bool_)) or
                                               not isinstance(i, (int, np.integer)) or
                                               i < 0 or i >= group_count for i in draw):
                raise ValueError("invalid group draw")
        draw_indices = [[int(i) for i in draw] for draw in draw_indices]
    if group_count < 2:
        draw_indices = []
    elif draw_indices is None:
        rng = np.random.Generator(np.random.PCG64(seed))
        draw_indices = [rng.integers(0, group_count, size=group_count, dtype=np.int64,
                                    endpoint=False).tolist() for _ in range(iterations)]
    values = {key: [] for key in _METRICS}
    for draw in draw_indices:
        counts = Counter(groups[index] for index in draw)
        stats = paired_statistics(rows, weights=[counts[r["dependency_group_id"]] for r in rows])
        for key in _METRICS:
            values[key].append(stats[key])
    intervals = {}
    attempted = len(draw_indices)
    for key, samples in values.items():
        valid_values = [v for v in samples if _finite(v)]
        failed = attempted - len(valid_values)
        estimated = attempted > 0 and failed == 0
        low, high = (_linear_quantile(valid_values, 0.025), _linear_quantile(valid_values, 0.975)) if estimated else (None, None)
        width = high - low if estimated else None
        if estimated and not all(_finite(v) for v in (low, high, width)):
            estimated = False
        intervals[key] = {"status": "estimated" if estimated else "not_estimable",
                          "lower": float(low) if estimated else None,
                          "upper": float(high) if estimated else None,
                          "width": float(width) if estimated else None,
                          "attempted": attempted, "valid": len(valid_values), "failed": failed,
                          "reason": None if estimated else ("insufficient_groups" if group_count < 2 else "invalid_draw_statistic_or_interval")}
    status = "estimated" if all(i["status"] == "estimated" for i in intervals.values()) else "not_estimable"
    return {"status": status, "seed": seed, "iterations": iterations, "attempted": attempted,
            "valid": min(i["valid"] for i in intervals.values()),
            "failed": max(i["failed"] for i in intervals.values()),
            "ordered_groups": groups, "draw_indices": draw_indices, "intervals": intervals}


def _linear_quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    left = math.floor(position)
    fraction = position - left
    if fraction == 0:
        return ordered[left]
    return (1 - fraction) * ordered[left] + fraction * ordered[left + 1]


def performance_decision(summary, intervals, thresholds, *, prerequisites, complete_output):
    """Gate clinical performance only when all required evidence is available."""
    missing, known_failures = [], []
    if not prerequisites:
        missing.append("prerequisites")
    if not complete_output:
        known_failures.append("incomplete_output")
    for key in ("n_patients", "n_groups"):
        if not _finite(summary.get(key)) or summary[key] <= 0 or (key == "n_groups" and summary[key] < 2):
            missing.append(key)
    required = ("max_mae", "min_mae_gain", "max_mae_ci_width", "max_gain_ci_width")
    for key in required:
        if not _finite(thresholds.get(key)):
            missing.append(key)
    for key in ("mae", "mae_gain"):
        if not _finite(summary.get(key)):
            missing.append(key)
        interval = intervals.get(key) or {}
        if interval.get("status") != "estimated" or any(not _finite(interval.get(field)) for field in ("lower", "upper", "width")):
            missing.append(f"{key}_ci")
    mae_ci, gain_ci = intervals.get("mae") or {}, intervals.get("mae_gain") or {}
    checks = (("mae_upper", mae_ci.get("upper"), thresholds.get("max_mae"), lambda x, t: x <= t),
              ("gain_lower_positive", gain_ci.get("lower"), 0, lambda x, t: x > t),
              ("gain_lower_threshold", gain_ci.get("lower"), thresholds.get("min_mae_gain"), lambda x, t: x >= t),
              ("mae_ci_width", mae_ci.get("width"), thresholds.get("max_mae_ci_width"), lambda x, t: x <= t),
              ("gain_ci_width", gain_ci.get("width"), thresholds.get("max_gain_ci_width"), lambda x, t: x <= t))
    for name, value, limit, passes in checks:
        if _finite(value) and _finite(limit) and not passes(value, limit):
            known_failures.append(name)
    return {"status": "not_assessable" if missing else ("not_met" if known_failures else "met"),
            "missing": missing, "known_failures": known_failures}
