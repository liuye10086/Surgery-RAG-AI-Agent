"""Deterministic feature extraction for longitudinal prediction.

The helpers in this module operate on plain dictionaries so they can be used
by API services, offline training scripts, and tests without a database
session.  A prefix is always built from visits at or before its ``as_of``
date; this is the boundary that prevents future-visit leakage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Any, Iterable


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
            "latest_reference_status": _reference_status(latest_raw, last),
        }
        display_name = str(raw[name][0].get("name") or "").strip()
        if display_name and display_name != name:
            indicator_summary[display_name] = dict(indicator_summary[name])
    missingness = {}
    for name, entries in raw.items():
        ratio = 1 - (len(observations.get(name, [])) / total_visits)
        missingness[name] = ratio
        display_name = str(entries[0].get("name") or "").strip()
        if display_name and display_name != name:
            missingness[display_name] = ratio
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
