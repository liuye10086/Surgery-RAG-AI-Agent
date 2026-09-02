"""Shared indicator validation contract for API, imports, and prediction inputs.

Clinical reference abnormalities are observations, not malformed input.  This
module only rejects structural errors, unsupported disease indicators, units,
non-finite numbers, duplicate indicators, and values outside conservative hard
data bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Any, Iterable


_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./+\-βΒτΤ]*$")


@dataclass(frozen=True)
class IndicatorDefinition:
    code: str
    units: tuple[str, ...]
    safe_min: float | None = None
    safe_max: float | None = None
    reference_min: float | None = None
    reference_max: float | None = None


@dataclass(frozen=True)
class ValidatedIndicator:
    code: str
    value: float
    unit: str
    safety_status: str
    clinical_status: str


@dataclass(frozen=True)
class IndicatorValidationResult:
    disease_code: str
    items: tuple[ValidatedIndicator, ...]
    is_valid: bool = True


class IndicatorValidationError(ValueError):
    pass


def _definition(
    code: str,
    units: str | tuple[str, ...],
    safe: tuple[float | None, float | None] = (0, None),
):
    normalized_units = (units,) if isinstance(units, str) else units
    return IndicatorDefinition(code, normalized_units, safe[0], safe[1])


_FATTY_LIVER = {
    "alt": _definition("alt", "U/L"),
    "ast": _definition("ast", "U/L"),
    "ggt": _definition("ggt", "U/L"),
    "tbil": _definition("tbil", ("μmol/L", "µmol/L", "umol/L")),
    "alb": _definition("alb", "g/L"),
    "plt": _definition("plt", ("10⁹/L", "10^9/L")),
    "hba1c": _definition("hba1c", "%"),
    "afp": _definition("afp", "ng/mL"),
    "waist": _definition("waist", "cm"),
    "bmi": _definition("bmi", ("kg/m²", "kg/m2")),
}

_AD = {
    "cdr": _definition("cdr", "分", (0, 3)),
    "mmse": _definition("mmse", "分", (0, 30)),
    "moca": _definition("moca", "分", (0, 30)),
    "abeta42": _definition("abeta42", "pg/mL"),
    "abeta40": _definition("abeta40", "pg/mL"),
    "abeta_ratio": _definition("abeta_ratio", ("比值", "ratio")),
    "ptau181": _definition("ptau181", "pg/mL"),
    "ttau": _definition("ttau", "pg/mL"),
    "plasma_ptau217": _definition("plasma_ptau217", "pg/mL"),
    "plasma_nfl": _definition("plasma_nfl", "pg/mL"),
    "gfap": _definition("gfap", "pg/mL"),
    "ykl40": _definition("ykl40", "ng/mL"),
    "strem2": _definition("strem2", "ng/mL"),
    "crp": _definition("crp", "mg/L"),
    "homocysteine": _definition(
        "homocysteine", ("μmol/L", "µmol/L", "umol/L")
    ),
}

INDICATOR_CONTRACTS = MappingProxyType(
    {
        "fatty_liver": MappingProxyType(_FATTY_LIVER),
        "ad": MappingProxyType(_AD),
    }
)


def allowed_indicator_codes(disease_code: str) -> tuple[str, ...]:
    try:
        return tuple(INDICATOR_CONTRACTS[disease_code])
    except KeyError as exc:
        raise IndicatorValidationError(f"不支持的疾病代码：{disease_code}") from exc


def default_unit(disease_code: str, indicator_code: str) -> str:
    try:
        return INDICATOR_CONTRACTS[disease_code][indicator_code.lower()].units[0]
    except KeyError as exc:
        raise IndicatorValidationError(
            f"疾病 {disease_code} 不支持指标 {indicator_code}"
        ) from exc


def _field(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _clinical_status(reference: dict[str, Any] | None, value: float) -> str:
    if not reference:
        return "not_assessed"
    lower = reference.get("lower")
    upper = reference.get("upper")
    if lower is not None and value < float(lower):
        return "below_reference"
    if upper is not None and value > float(upper):
        return "above_reference"
    if lower is None and upper is None:
        return "not_assessed"
    return "within_reference"


def validate_indicators(
    disease_code: str,
    indicators: Iterable[Any],
    *,
    reference_ranges: dict[str, dict[str, Any]] | None = None,
) -> IndicatorValidationResult:
    try:
        definitions = INDICATOR_CONTRACTS[disease_code]
    except KeyError as exc:
        raise IndicatorValidationError(f"不支持的疾病代码：{disease_code}") from exc

    validated: list[ValidatedIndicator] = []
    seen: set[str] = set()
    for index, item in enumerate(indicators, start=1):
        raw_name = _field(item, "name")
        name = raw_name.strip().lower() if isinstance(raw_name, str) else ""
        if not name:
            raise IndicatorValidationError(f"第 {index} 个指标名称不能为空")
        if not _NAME_RE.fullmatch(name):
            raise IndicatorValidationError(f"指标名称格式无效：{raw_name}")
        if name in seen:
            raise IndicatorValidationError(f"同一次访视不能重复指标：{name}")
        seen.add(name)

        definition = definitions.get(name)
        if definition is None:
            owner = next(
                (code for code, entries in INDICATOR_CONTRACTS.items() if name in entries),
                None,
            )
            if owner:
                raise IndicatorValidationError(
                    f"指标 {name} 属于疾病 {owner}，不属于当前疾病 {disease_code}"
                )
            raise IndicatorValidationError(
                f"未知指标 {name}；当前疾病 {disease_code} 不支持该指标"
            )

        raw_unit = _field(item, "unit")
        unit = raw_unit.strip() if isinstance(raw_unit, str) else ""
        if not unit:
            raise IndicatorValidationError(f"指标 {name} 的单位不能为空")
        if unit not in definition.units:
            expected = "、".join(definition.units)
            raise IndicatorValidationError(
                f"指标 {name} 的单位 {unit} 不合法，应使用：{expected}"
            )

        raw_value = _field(item, "value")
        if isinstance(raw_value, bool):
            raise IndicatorValidationError(f"指标 {name} 的数值必须是有限数字")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise IndicatorValidationError(
                f"指标 {name} 的数值必须是有限数字"
            ) from exc
        if not math.isfinite(value):
            raise IndicatorValidationError(f"指标 {name} 的数值必须是有限数字")
        if definition.safe_min is not None and value < definition.safe_min:
            raise IndicatorValidationError(
                f"指标 {name} 的数值 {value:g} 超出安全数据范围"
            )
        if definition.safe_max is not None and value > definition.safe_max:
            raise IndicatorValidationError(
                f"指标 {name} 的数值 {value:g} 超出安全数据范围"
            )

        validated.append(
            ValidatedIndicator(
                code=name,
                value=value,
                unit=unit,
                safety_status="within_safe_range",
                clinical_status=_clinical_status(
                    (reference_ranges or {}).get(name), value
                ),
            )
        )

    return IndicatorValidationResult(disease_code, tuple(validated))


def validate_visits(disease_code: str, visits: Iterable[Any]) -> None:
    for index, visit in enumerate(visits, start=1):
        indicators = _field(visit, "indicators") or []
        try:
            validate_indicators(disease_code, indicators)
        except IndicatorValidationError as exc:
            raise IndicatorValidationError(f"第 {index} 次访视：{exc}") from exc
