"""Deterministic interpretation of longitudinal observation signals."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.schemas.longitudinal_model_registry import ModelRuntimeStatus
from app.schemas.longitudinal_report import (
    LongitudinalSignal,
    SignalInterpretationResult,
)
from app.services.longitudinal_features import sort_visits


FATTY_LIVER_SIGNAL_CONFIG = MappingProxyType(
    {
        "alt": ("谷丙转氨酶", "rising"),
        "ast": ("谷草转氨酶", "rising"),
        "ggt": ("γ-谷氨酰转肽酶", "rising"),
        "tbil": ("总胆红素", "rising"),
        "alb": ("白蛋白", "falling"),
        "hba1c": ("糖化血红蛋白", "rising"),
        "waist": ("腰围", "rising"),
        "plt": ("血小板计数", "falling"),
        "afp": ("甲胎蛋白", "rising"),
        "bmi": ("体质指数", "rising"),
    }
)

AD_SIGNAL_CONFIG = MappingProxyType(
    {
        "mmse": ("简易精神状态检查", "falling"),
        "moca": ("蒙特利尔认知评估", "falling"),
        "cdr": ("临床痴呆评定", "rising"),
        "nfl": ("神经丝轻链", "rising"),
        "p-tau217": ("磷酸化 tau217", "rising"),
        "aβ42/aβ40": ("β淀粉样蛋白 42/40 比值", "falling"),
    }
)

_CONFIGS = MappingProxyType(
    {"fatty_liver": FATTY_LIVER_SIGNAL_CONFIG, "ad": AD_SIGNAL_CONFIG}
)
_ALIASES = MappingProxyType(
    {
        "fatty_liver": MappingProxyType(
            {name: name for name in FATTY_LIVER_SIGNAL_CONFIG}
        ),
        "ad": MappingProxyType(
            {
                "mmse": "mmse",
                "moca": "moca",
                "cdr": "cdr",
                "nfl": "nfl",
                "plasma_nfl": "nfl",
                "p-tau217": "p-tau217",
                "plasma_ptau217": "p-tau217",
                "aβ42/aβ40": "aβ42/aβ40",
                "abeta_ratio": "aβ42/aβ40",
            }
        ),
    }
)

_APPROVED_UNITS = MappingProxyType(
    {
        "alt": frozenset({"U/L"}),
        "ast": frozenset({"U/L"}),
        "ggt": frozenset({"U/L"}),
        "tbil": frozenset({"μmol/L"}),
        "alb": frozenset({"g/L"}),
        "hba1c": frozenset({"%"}),
        "waist": frozenset({"cm"}),
        "plt": frozenset({"10⁹/L"}),
        "afp": frozenset({"ng/mL"}),
        "bmi": frozenset({"kg/m²"}),
        "mmse": frozenset({"分"}),
        "moca": frozenset({"分"}),
        "cdr": frozenset({"分"}),
        "nfl": frozenset({"pg/mL"}),
        "p-tau217": frozenset({"pg/mL"}),
        "aβ42/aβ40": frozenset({"ratio"}),
    }
)

_REASON_ORDER = MappingProxyType(
    {
        code: index
        for index, code in enumerate(
            (
                "insufficient_observations",
                "missing_value",
                "non_finite_value",
                "unit_missing",
                "unit_conflict",
                "unsupported_unit",
                "directional_change",
                "persistent_direction",
                "reference_unavailable",
                "reference_not_applicable",
                "latest_above_reference",
                "latest_below_reference",
                "feature_not_used",
                "model_unavailable",
                "contribution_unavailable",
            )
        )
    }
)


@dataclass(frozen=True)
class ReferenceInterpretation:
    status: str
    reason_code: str | None = None
    rule_id: int | None = None
    version_id: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()


def canonicalize_indicator(
    dataset: str, raw_name: str
) -> tuple[str | None, str | None]:
    """Return an explicitly approved canonical key and display name."""
    normalized_dataset = str(dataset).strip().lower()
    aliases = _ALIASES.get(normalized_dataset)
    if aliases is None:
        return None, None
    canonical = aliases.get(str(raw_name or "").strip().lower())
    if canonical is None:
        return None, None
    display_name = _CONFIGS[normalized_dataset][canonical][0]
    return canonical, display_name


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _direction(first: float, latest: float) -> str:
    if latest > first:
        return "rising"
    if latest < first:
        return "falling"
    return "stable"


def _persistent(values: list[float], direction: str) -> bool:
    if direction == "rising":
        return all(current > previous for previous, current in zip(values, values[1:]))
    if direction == "falling":
        return all(current < previous for previous, current in zip(values, values[1:]))
    return False


def _unit_state(
    canonical: str, entries: list[tuple[date, float, str | None, str]]
) -> tuple[str, str | None]:
    units = [entry[2] for entry in entries]
    present = {unit for unit in units if unit is not None}
    if len(present) > 1:
        return "unit_conflict", None
    if any(unit is None for unit in units):
        return "unit_missing", next(iter(present), None)
    unit = next(iter(present))
    if unit not in _APPROVED_UNITS.get(canonical, frozenset()):
        return "unsupported_unit", unit
    return "supported", unit


def _matching_standard_sources(
    dataset: str,
    canonical: str,
    standard_sources: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    matches = []
    for source in standard_sources:
        source_canonical, _ = canonicalize_indicator(
            dataset, str(source.get("indicator") or "")
        )
        if source_canonical == canonical:
            matches.append(source)
    return sorted(
        matches,
        key=lambda source: (
            int(source.get("standard_version_id") or 0),
            int(source.get("standard_rule_id") or 0),
            str(source.get("source_type") or ""),
        ),
    )


def _safe_provenance(
    canonical: str, source: Mapping[str, Any] | None, unit_state: str
) -> dict[str, Any]:
    provenance = {
        "canonical_indicator": canonical,
        "unit_decision": unit_state,
    }
    if source is None:
        return provenance
    for key in (
        "source_type",
        "standard_version_id",
        "standard_rule_id",
        "applicability_hash",
        "machine_actionability",
    ):
        if source.get(key) is not None:
            provenance[key] = source[key]
    return provenance


def _resolve_reference_state(
    *,
    dataset: str,
    canonical: str,
    latest_value: float,
    unit_state: str,
    unit: str | None,
    standard_sources: Sequence[Mapping[str, Any]],
) -> ReferenceInterpretation:
    matches = _matching_standard_sources(dataset, canonical, standard_sources)
    source = matches[0] if matches else None
    if unit_state == "unit_missing":
        return ReferenceInterpretation(
            status="unit_missing",
            reason_code="unit_missing",
            provenance=_safe_provenance(canonical, source, unit_state),
            limitations=("指标单位缺失，未进行参考范围判断",),
        )
    if unit_state == "unsupported_unit":
        return ReferenceInterpretation(
            status="unsupported_unit",
            reason_code="unsupported_unit",
            provenance=_safe_provenance(canonical, source, unit_state),
            limitations=("指标单位不在已批准单位清单中，未进行参考范围判断",),
        )

    evidence = [
        item
        for item in matches
        if item.get("source_type") == "standard_evidence"
        or item.get("machine_actionability") == "evidence-only"
    ]
    calculable_sources = [
        item
        for item in matches
        if item.get("source_type") == "reference_range"
        and item.get("machine_actionability", "calculable") == "calculable"
    ]
    calculable = [
        item
        for item in calculable_sources
        if str(item.get("unit") or "").strip() == unit
    ]
    if calculable_sources and not calculable:
        selected = calculable_sources[0]
        return ReferenceInterpretation(
            status="unsupported_unit",
            reason_code="unsupported_unit",
            provenance=_safe_provenance(canonical, selected, "unsupported_unit"),
            limitations=("指标单位与正式参考范围单位不一致，未进行范围判断",),
        )
    if len(calculable) != 1:
        selected = evidence[0] if evidence else source
        status = "reference_not_applicable" if matches else "reference_unavailable"
        limitation = (
            "当前标准仅提供证据说明，不支持数值范围判断"
            if evidence
            else "当前没有唯一适用的可计算参考范围"
        )
        return ReferenceInterpretation(
            status=status,
            reason_code=status,
            rule_id=selected.get("standard_rule_id") if selected else None,
            version_id=selected.get("standard_version_id") if selected else None,
            provenance=_safe_provenance(canonical, selected, unit_state),
            limitations=(limitation,),
        )

    selected = calculable[0]
    lower = _finite_float(selected.get("lower"))
    upper = _finite_float(selected.get("upper"))
    if lower is None and upper is None:
        return ReferenceInterpretation(
            status="reference_not_applicable",
            reason_code="reference_not_applicable",
            rule_id=selected.get("standard_rule_id"),
            version_id=selected.get("standard_version_id"),
            provenance=_safe_provenance(canonical, selected, unit_state),
            limitations=("正式规则没有可计算边界，未进行范围判断",),
        )
    below = lower is not None and (
        latest_value < lower
        or (latest_value == lower and not selected.get("lower_inclusive", True))
    )
    above = upper is not None and (
        latest_value > upper
        or (latest_value == upper and not selected.get("upper_inclusive", True))
    )
    status = "below_range" if below else "above_range" if above else "within_range"
    return ReferenceInterpretation(
        status=status,
        reason_code=(
            "latest_below_reference"
            if below
            else "latest_above_reference"
            if above
            else None
        ),
        rule_id=selected.get("standard_rule_id"),
        version_id=selected.get("standard_version_id"),
        provenance=_safe_provenance(canonical, selected, unit_state),
    )


def map_signal_model_features(
    canonical_indicator: str,
    *,
    raw_indicator: str,
    outcome_status: ModelRuntimeStatus | None,
    feature_names: Sequence[str] | None,
) -> tuple[bool, list[str], list[str]]:
    """Map one raw indicator to exact artifact feature prefixes."""
    del canonical_indicator
    if outcome_status is None or outcome_status.status != "available":
        return False, [], ["model_unavailable"]
    prefix = f"{str(raw_indicator).strip().lower()}."
    matched = sorted(
        feature
        for feature in feature_names or []
        if isinstance(feature, str) and feature.startswith(prefix)
    )
    if not matched:
        return False, [], ["feature_not_used"]
    return True, matched, []


def _ordered_reasons(reason_codes: Sequence[str]) -> list[str]:
    return sorted(
        set(reason_codes),
        key=lambda code: (_REASON_ORDER.get(code, len(_REASON_ORDER)), code),
    )


def _signal_sort_key(
    signal: LongitudinalSignal, canonical_order: Mapping[str, int]
) -> tuple[int, int, float, int, str]:
    level_rank = {"priority": 2, "attention": 1, "none": 0}
    abnormal_rank = int(signal.reference_status in {"above_range", "below_range"})
    return (
        -level_rank[signal.attention_level],
        -abnormal_rank,
        -abs(signal.relative_change or 0.0),
        canonical_order.get(signal.indicator, 10_000),
        signal.indicator,
    )


def interpret_observation_signals(
    *,
    dataset: str,
    visits: Sequence[Mapping[str, Any]],
    standard_sources: Sequence[Mapping[str, Any]] | None = None,
    outcome_status: ModelRuntimeStatus | None = None,
    feature_names: Sequence[str] | None = None,
) -> SignalInterpretationResult:
    """Interpret key signals without model inference or clinical guessing."""
    standard_sources = list(standard_sources or [])
    dataset = str(dataset).strip().lower()
    config = _CONFIGS.get(dataset)
    if config is None:
        return SignalInterpretationResult(
            summary={"signal_count": 0, "reason": "unsupported_dataset"}
        )

    ordered = sort_visits([dict(visit) for visit in visits])
    observations: dict[str, list[tuple[date, float, str | None, str]]] = defaultdict(list)
    invalid: dict[str, list[str]] = defaultdict(list)
    for visit in ordered:
        visit_date = date.fromisoformat(visit["visit_date"])
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, Mapping):
                continue
            raw_name = str(indicator.get("name") or "").strip()
            canonical, _ = canonicalize_indicator(dataset, raw_name)
            if canonical is None:
                continue
            value = _finite_float(indicator.get("value"))
            if value is None:
                reason = (
                    "missing_value"
                    if indicator.get("value") is None
                    else "non_finite_value"
                )
                if reason not in invalid[canonical]:
                    invalid[canonical].append(reason)
                continue
            unit = str(indicator.get("unit") or "").strip() or None
            observations[canonical].append((visit_date, value, unit, raw_name.lower()))

    signals: list[LongitudinalSignal] = []
    omitted: list[dict[str, Any]] = []
    for canonical in config:
        entries = observations.get(canonical, [])
        if len(entries) < 3:
            if entries or canonical in invalid:
                omitted.append(
                    {
                        "indicator": canonical,
                        "reason_codes": [
                            *invalid.get(canonical, []),
                            "insufficient_observations",
                        ],
                        "observation_count": len(entries),
                    }
                )
            continue

        values = [entry[1] for entry in entries]
        observed_direction = _direction(values[0], values[-1])
        attention_direction = config[canonical][1]
        if observed_direction != attention_direction:
            omitted.append(
                {
                    "indicator": canonical,
                    "reason_codes": ["direction_not_attention"],
                    "observation_count": len(entries),
                }
            )
            continue

        reasons = [*invalid.get(canonical, []), "directional_change"]
        if _persistent(values, observed_direction):
            reasons.append("persistent_direction")
        used_by_model, model_features, model_reasons = map_signal_model_features(
            canonical,
            raw_indicator=entries[0][3],
            outcome_status=outcome_status,
            feature_names=feature_names,
        )
        reasons.extend(model_reasons)
        unit_state, unit = _unit_state(canonical, entries)
        if unit_state == "unit_conflict":
            omitted.append(
                {
                    "indicator": canonical,
                    "reason_codes": [*reasons, "unit_conflict"],
                    "observation_count": len(entries),
                }
            )
            continue
        reference = _resolve_reference_state(
            dataset=dataset,
            canonical=canonical,
            latest_value=values[-1],
            unit_state=unit_state,
            unit=unit,
            standard_sources=standard_sources,
        )
        if reference.reason_code:
            reasons.append(reference.reason_code)
        reasons.append("contribution_unavailable")
        limitations = list(reference.limitations)
        if canonical == "cdr":
            limitations.append("CDR 仅作为阶段相关观察，不是阶段模型结论")
        signals.append(
            LongitudinalSignal(
                indicator=canonical,
                display_name=config[canonical][0],
                unit=unit,
                first_value=values[0],
                latest_value=values[-1],
                absolute_change=values[-1] - values[0],
                relative_change=(
                    None if values[0] == 0 else (values[-1] - values[0]) / values[0]
                ),
                observation_count=len(entries),
                observation_span_days=(entries[-1][0] - entries[0][0]).days,
                observed_direction=observed_direction,
                disease_attention_direction=attention_direction,
                reference_status=reference.status,
                reference_rule_id=reference.rule_id,
                reference_version_id=reference.version_id,
                attention_level=(
                    "priority"
                    if reference.status in {"above_range", "below_range"}
                    else "attention"
                ),
                reason_codes=_ordered_reasons(reasons),
                used_by_outcome_model=used_by_model,
                model_feature_names=model_features,
                model_contribution_status=(
                    "not_supported"
                    if outcome_status is not None and outcome_status.status == "available"
                    else "unavailable"
                ),
                provenance={
                    "observation_source": "visits",
                    **reference.provenance,
                },
                limitations=limitations,
            )
        )

    canonical_order = {name: index for index, name in enumerate(config)}
    signals.sort(key=lambda signal: _signal_sort_key(signal, canonical_order))
    return SignalInterpretationResult(
        signals=signals,
        omitted_indicators=omitted,
        summary={
            "signal_count": len(signals),
            "omitted_count": len(omitted),
            "minimum_observations": 3,
            "summary_code": (
                "signals_available" if signals else "insufficient_key_signals"
            ),
        },
    )


__all__ = [
    "canonicalize_indicator",
    "interpret_observation_signals",
    "map_signal_model_features",
]
