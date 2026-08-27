"""Deterministic feature extraction for longitudinal prediction.

The helpers in this module operate on plain dictionaries so they can be used
by API services, offline training scripts, and tests without a database
session.  A prefix is always built from visits at or before its ``as_of``
date; this is the boundary that prevents future-visit leakage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from itertools import pairwise
from math import isfinite
from statistics import fmean
from typing import Any, Iterable

from app.schemas.longitudinal_model_registry import ArtifactMetadata


class InferenceContractError(ValueError):
    """Privacy-safe failure in the online feature contract."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _visit_date(value: Any) -> date:
    """Normalize supported date representations to a calendar date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("访视缺少 visit_date")
    # ISO datetimes are accepted in addition to the API's ISO date values.
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError(f"无效的访视日期: {value!r}") from exc


def _as_finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def sort_visits(visits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return visits in ascending date order and reject duplicate dates.

    Duplicate dates are ambiguous for historical prefixes and therefore fail
    explicitly instead of relying on insertion order.  Returned mappings are
    shallow copies, so callers cannot accidentally mutate their input list.
    """
    ordered = []
    seen: set[date] = set()
    for visit in visits:
        if not isinstance(visit, dict):
            raise ValueError("访视必须是对象")
        parsed = _visit_date(visit.get("visit_date"))
        if parsed in seen:
            raise ValueError(f"访视日期重复: {parsed.isoformat()}")
        seen.add(parsed)
        copy = dict(visit)
        copy["visit_date"] = parsed.isoformat()
        ordered.append((parsed, copy))
    ordered.sort(key=lambda item: item[0])
    return [item[1] for item in ordered]


def build_prefixes(
    visits: Iterable[dict[str, Any]], minimum_visits: int = 2
) -> list[dict[str, Any]]:
    """Build one historical prefix for every visit after the minimum.

    The first prefix contains exactly ``minimum_visits`` rows, and each later
    prefix appends one observed visit.  No row after ``as_of`` is included.
    """
    if minimum_visits < 1:
        raise ValueError("minimum_visits 必须大于等于 1")
    ordered = sort_visits(visits)
    if len(ordered) < minimum_visits:
        return []
    return [
        {
            "as_of": ordered[index]["visit_date"],
            "visits": [dict(item) for item in ordered[: index + 1]],
        }
        for index in range(minimum_visits - 1, len(ordered))
    ]


def _indicator_observations(
    visits: Iterable[dict[str, Any]],
) -> tuple[
    dict[str, list[tuple[int, float]]],
    dict[str, list[dict[str, Any]]],
]:
    observations: dict[str, list[tuple[int, float]]] = defaultdict(list)
    raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for visit_index, visit in enumerate(visits):
        visit_names: set[str] = set()
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, dict):
                continue
            name = str(indicator.get("name") or "").strip().lower()
            value = _as_finite_float(indicator.get("value"))
            if not name:
                continue
            if name in visit_names:
                raise ValueError(
                    f"同一访视不能重复使用指标: {indicator.get('name')}"
                )
            visit_names.add(name)
            raw[name].append(indicator)
            if value is not None:
                observations[name].append((visit_index, value))
    return observations, raw


def _slope(observations: list[tuple[int, float]]) -> float | None:
    if len(observations) < 2:
        return None
    x_mean = sum(x for x, _ in observations) / len(observations)
    y_mean = sum(y for _, y in observations) / len(observations)
    denominator = sum((x - x_mean) ** 2 for x, _ in observations)
    if denominator == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in observations) / denominator


def _time_slope(observations: list[tuple[int, float]]) -> float | None:
    """Return an OLS slope per calendar day for dated observations."""
    if len(observations) < 2:
        return None
    x_mean = sum(day for day, _ in observations) / len(observations)
    y_mean = sum(value for _, value in observations) / len(observations)
    denominator = sum((day - x_mean) ** 2 for day, _ in observations)
    if denominator == 0:
        return None
    numerator = sum(
        (day - x_mean) * (value - y_mean) for day, value in observations
    )
    return numerator / denominator


def _reference_status(indicator: dict[str, Any], value: float) -> str:
    """Classify a value when the input carries optional reference bounds."""
    lower = indicator.get("lower", indicator.get("reference_lower"))
    upper = indicator.get("upper", indicator.get("reference_upper"))
    ref = indicator.get("reference_range")
    if isinstance(ref, dict):
        lower = ref.get("lower", lower)
        upper = ref.get("upper", upper)
    lower_value = _as_finite_float(lower)
    upper_value = _as_finite_float(upper)
    if lower_value is None and upper_value is None:
        return "unknown"
    lower_inclusive = indicator.get("lower_inclusive", True)
    upper_inclusive = indicator.get("upper_inclusive", True)
    if lower_value is not None and (
        value < lower_value or (value == lower_value and not lower_inclusive)
    ):
        return "below_range"
    if upper_value is not None and (
        value > upper_value or (value == upper_value and not upper_inclusive)
    ):
        return "above_range"
    return "within_range"


def _has_reference_bounds(indicator: dict[str, Any]) -> bool:
    ref = indicator.get("reference_range")
    if isinstance(ref, dict):
        return any(ref.get(key) is not None for key in ("lower", "upper"))
    return any(
        indicator.get(key) is not None
        for key in ("lower", "upper", "reference_lower", "reference_upper")
    )


def summarize_observation(visits: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize observed history, missingness, deltas and latest status."""
    ordered = sort_visits(visits)
    observations, raw = _indicator_observations(ordered)
    indicator_summary: dict[str, dict[str, Any]] = {}
    total_visits = len(ordered)
    for name, values_with_index in observations.items():
        values = [value for _, value in values_with_index]
        series = []
        units: set[str] = set()
        has_missing_unit = False
        for visit in ordered:
            for indicator in visit.get("indicators") or []:
                if str(indicator.get("name") or "").strip().lower() != name:
                    continue
                value = _as_finite_float(indicator.get("value"))
                if value is None:
                    continue
                unit = str(indicator.get("unit") or "").strip() or None
                if unit is None:
                    has_missing_unit = True
                else:
                    units.add(unit)
                series.append(
                    {
                        "visit_date": visit["visit_date"],
                        "value": value,
                        "unit": unit,
                    }
                )
        unit_state = (
            "conflict"
            if len(units) > 1
            else "missing"
            if has_missing_unit
            else "consistent"
        )
        first, last = values[0], values[-1]
        delta = last - first
        # Use the latest valid observation and carry forward the nearest
        # reference metadata when a later visit omits the range fields.
        latest_raw = next(
            (
                item
                for item in reversed(raw[name])
                if _as_finite_float(item.get("value")) is not None
            ),
            raw[name][-1],
        )
        if not _has_reference_bounds(latest_raw):
            latest_raw = next(
                (item for item in reversed(raw[name]) if _has_reference_bounds(item)),
                latest_raw,
            )
        indicator_summary[name] = {
            "first": first,
            "last": last,
            "delta": delta,
            "delta_pct": None if first == 0 else delta / first,
            "slope": _slope(values_with_index),
            "rises_count": sum(a < b for a, b in zip(values, values[1:])),
            "falls_count": sum(a > b for a, b in zip(values, values[1:])),
            "n_observations": len(values),
            "unit": next(iter(units), None) if unit_state == "consistent" else None,
            "unit_state": unit_state,
            "series": series,
            "latest_reference_status": _reference_status(latest_raw, last),
        }
    missingness = {}
    for name, entries in raw.items():
        ratio = 1 - (len(observations.get(name, [])) / total_visits)
        missingness[name] = ratio
    first_date = _visit_date(ordered[0]["visit_date"]) if ordered else None
    last_date = _visit_date(ordered[-1]["visit_date"]) if ordered else None
    return {
        "visit_count": total_visits,
        "observation_span_days": (last_date - first_date).days
        if first_date and last_date
        else 0,
        "first_visit_date": first_date.isoformat() if first_date else None,
        "last_visit_date": last_date.isoformat() if last_date else None,
        "missingness_summary": missingness,
        "indicators": indicator_summary,
    }


def summarize_fixed_window_history(
    visits: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize one already-truncated prefix using real calendar time."""
    ordered = sort_visits(visits)
    total_visits = len(ordered)
    if total_visits == 0:
        return {
            "visit_count": 0,
            "observation_span_days": 0,
            "days_since_previous_visit": 0,
            "indicators": {},
        }

    first_date = _visit_date(ordered[0]["visit_date"])
    last_date = _visit_date(ordered[-1]["visit_date"])
    previous_date = (
        _visit_date(ordered[-2]["visit_date"])
        if total_visits >= 2
        else last_date
    )

    values_by_name: dict[str, list[tuple[int, float]]] = defaultdict(list)
    known_names: set[str] = set()
    for visit in ordered:
        visit_date = _visit_date(visit["visit_date"])
        seen_names: set[str] = set()
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, dict):
                continue
            name = str(indicator.get("name") or "").strip().lower()
            if not name:
                continue
            if name in seen_names:
                raise ValueError(
                    f"同一访视不能重复使用指标: {indicator.get('name')}"
                )
            seen_names.add(name)
            known_names.add(name)
            value = _as_finite_float(indicator.get("value"))
            if value is not None:
                values_by_name[name].append(
                    ((visit_date - first_date).days, value)
                )

    summaries: dict[str, dict[str, Any]] = {}
    for name in sorted(known_names):
        observations = values_by_name.get(name, [])
        if not observations:
            continue
        values = [value for _, value in observations]
        summaries[name] = {
            "first": values[0],
            "last": values[-1],
            "minimum": min(values),
            "maximum": max(values),
            "mean": fmean(values),
            "delta": values[-1] - values[0],
            "time_slope_per_day": _time_slope(observations),
            "recent_delta": (
                values[-1] - values[-2] if len(values) >= 2 else None
            ),
            "rises_count": sum(first < second for first, second in pairwise(values)),
            "falls_count": sum(first > second for first, second in pairwise(values)),
            "n_observations": len(values),
            "missing_ratio": 1 - (len(values) / total_visits),
        }

    return {
        "visit_count": total_visits,
        "observation_span_days": (last_date - first_date).days,
        "days_since_previous_visit": (last_date - previous_date).days,
        "indicators": summaries,
    }


def build_feature_vector(
    visits: Iterable[dict[str, Any]], feature_names: Iterable[str]
) -> list[float]:
    """Build a model-ordered vector from the supplied visits.

    Feature names use the existing ``indicator.stat`` convention.  Missing
    values are represented as NaN so a model's configured imputer can handle
    them; this matches the legacy progression engine contract.
    """
    summary = summarize_observation(visits)["indicators"]
    vector: list[float] = []
    for feature_name in feature_names:
        try:
            indicator_name, statistic = str(feature_name).rsplit(".", 1)
        except ValueError as exc:
            raise ValueError(f"无效的特征名: {feature_name!r}") from exc
        value = summary.get(indicator_name.strip().lower(), {}).get(statistic)
        vector.append(float(value) if value is not None else float("nan"))
    return vector


def _reject_non_finite_inputs(visits: Iterable[dict[str, Any]]) -> None:
    for visit in visits:
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, dict):
                continue
            raw = indicator.get("value")
            if raw is None:
                continue
            if isinstance(raw, bool):
                raise InferenceContractError("non_finite_feature")
            try:
                numeric = float(raw)
            except (TypeError, ValueError) as exc:
                raise InferenceContractError("non_finite_feature") from exc
            if not isfinite(numeric):
                raise InferenceContractError("non_finite_feature")


def build_fixed_window_inference_features(
    case: dict[str, Any],
    visits: Iterable[dict[str, Any]],
    metadata: ArtifactMetadata,
):
    """Build one P0-04-compatible, metadata-ordered inference DataFrame."""
    import pandas as pd

    visit_rows = list(visits)
    _reject_non_finite_inputs(visit_rows)
    contract = metadata.feature_contract
    if contract.input_container != "pandas_dataframe":
        raise InferenceContractError("input_container_mismatch")
    if not contract.feature_names or len(contract.feature_names) != len(
        set(contract.feature_names)
    ):
        raise InferenceContractError("feature_names_invalid")

    summary = summarize_fixed_window_history(visit_rows)
    values: dict[str, Any] = {
        "age": None,
        "sex": case.get("sex"),
        "visit_count": summary["visit_count"],
        "observation_span_days": summary["observation_span_days"],
        "days_since_previous_visit": summary["days_since_previous_visit"],
    }
    for indicator_name, indicator in summary["indicators"].items():
        for statistic, value in indicator.items():
            values[f"{indicator_name}.{statistic}"] = value

    row = {name: values.get(name) for name in contract.feature_names}
    for name in contract.required_features:
        value = row.get(name)
        if value is None or (isinstance(value, float) and not isfinite(value)):
            raise InferenceContractError("required_feature_missing")
    allowed_missing = set(contract.allowed_missing_features)
    for name, value in row.items():
        if value is None:
            if name not in allowed_missing:
                raise InferenceContractError("required_feature_missing")
            continue
        if name in contract.numeric_features:
            if isinstance(value, bool):
                raise InferenceContractError("non_finite_feature")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise InferenceContractError("non_finite_feature") from exc
            if not isfinite(numeric):
                raise InferenceContractError("non_finite_feature")
            row[name] = numeric

    frame = pd.DataFrame([row], columns=contract.feature_names)
    if list(frame.columns) != contract.feature_names:
        raise InferenceContractError("feature_order_mismatch")
    return frame
