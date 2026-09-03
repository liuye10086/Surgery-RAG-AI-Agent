"""Central validation and normalization for operator-owned case writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from app.services.indicator_validation import (
    IndicatorValidationError,
    validate_indicators,
)
from app.schemas.operator_visit_context import VisitContext
from app.services.longitudinal_task_routing import normalize_baseline_stage


STABLE_STAGES = {
    "fatty_liver": frozenset(
        {"pre_cirrhosis", "suspected_cirrhosis", "cirrhosis", "hcc"}
    ),
    "ad": frozenset({"normal", "mci", "pre_dementia", "dementia"}),
}


class OperatorCaseValidationError(ValueError):
    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True)
class NormalizedVisit:
    visit_date: date
    visit_index: int
    indicators: tuple[dict[str, Any], ...]
    notes: str | None
    visit_context: dict[str, Any]

    def as_orm_kwargs(self) -> dict[str, Any]:
        return {
            "visit_date": self.visit_date,
            "visit_index": self.visit_index,
            "indicators": [dict(item) for item in self.indicators],
            "notes": self.notes,
        }


def _field(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def validate_operator_case_profile(
    disease_code: str,
    age: Any,
    sex: Any,
    baseline_stage: Any,
) -> str:
    if isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 120:
        raise OperatorCaseValidationError(
            "age_invalid",
            "年龄必须为 0–120 的整数",
            field="age",
        )
    if sex not in {"male", "female"}:
        raise OperatorCaseValidationError(
            "sex_invalid",
            "性别必须选择 male 或 female",
            field="sex",
        )
    if baseline_stage is None or not str(baseline_stage).strip():
        raise OperatorCaseValidationError(
            "baseline_stage_missing",
            "请选择确定的基线阶段",
            field="baseline_stage",
        )
    if disease_code not in STABLE_STAGES:
        raise OperatorCaseValidationError(
            "disease_unsupported",
            "当前疾病不支持病例工作区",
            field="disease_id",
        )

    raw_stage = str(baseline_stage).strip()
    route = normalize_baseline_stage(disease_code, raw_stage)
    normalized = route.normalized_stage
    if normalized is None:
        code = (
            "baseline_stage_disease_conflict"
            if route.reason_code == "baseline_stage_disease_conflict"
            else route.reason_code
        )
        raise OperatorCaseValidationError(
            code,
            "基线阶段不属于当前疾病",
            field="baseline_stage",
        )
    if raw_stage != normalized:
        raise OperatorCaseValidationError(
            "baseline_stage_stable_code_required",
            "基线阶段必须使用稳定英文代码",
            field="baseline_stage",
        )
    if normalized not in STABLE_STAGES[disease_code]:
        raise OperatorCaseValidationError(
            "baseline_stage_disease_conflict",
            "基线阶段不属于当前疾病",
            field="baseline_stage",
        )
    return normalized


def _as_date(value: Any, *, index: int) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise OperatorCaseValidationError(
            "visit_date_invalid",
            f"第 {index + 1} 次访视日期无效",
            field=f"visits.{index}.visit_date",
        ) from exc


def normalize_operator_timeline(
    disease_code: str,
    visits: Iterable[Any],
) -> list[NormalizedVisit]:
    raw_visits = list(visits)
    if not 1 <= len(raw_visits) <= 10:
        raise OperatorCaseValidationError(
            "visit_count_invalid",
            "病例必须包含 1–10 次访视",
            field="visits",
        )

    prepared: list[tuple[date, tuple[dict[str, Any], ...], str | None]] = []
    seen_dates: set[date] = set()
    for index, visit in enumerate(raw_visits):
        visit_date = _as_date(_field(visit, "visit_date"), index=index)
        if visit_date in seen_dates:
            raise OperatorCaseValidationError(
                "duplicate_visit_date",
                "同一病例不能重复使用访视日期",
                field=f"visits.{index}.visit_date",
            )
        seen_dates.add(visit_date)

        indicators = list(_field(visit, "indicators") or [])
        if not 1 <= len(indicators) <= 30:
            raise OperatorCaseValidationError(
                "indicator_count_invalid",
                "每次访视必须包含 1–30 个指标",
                field=f"visits.{index}.indicators",
            )
        for indicator_index, indicator in enumerate(indicators):
            if _field(indicator, "value") is None:
                raise OperatorCaseValidationError(
                    "indicator_value_missing",
                    "指标数值不能为空",
                    field=f"visits.{index}.indicators.{indicator_index}.value",
                )
        try:
            result = validate_indicators(disease_code, indicators)
        except IndicatorValidationError as exc:
            raise OperatorCaseValidationError(
                "invalid_indicators",
                str(exc),
                field=f"visits.{index}.indicators",
            ) from exc
        normalized_indicators = tuple(
            sorted(
                (
                    {"name": item.code, "value": item.value, "unit": item.unit}
                    for item in result.items
                ),
                key=lambda item: item["name"],
            )
        )
        raw_context = _field(visit, "visit_context")
        try:
            context = VisitContext.model_validate(raw_context or {})
        except Exception as exc:
            errors = getattr(exc, "errors", lambda: [])()
            suffix = errors[0].get("loc", ("visit_context",)) if errors else ("visit_context",)
            field = ".".join([f"visits.{index}", *(str(item) for item in suffix)])
            raise OperatorCaseValidationError(
                "visit_context_invalid",
                "访视检测上下文无效",
                field=field,
            ) from exc
        raw_notes = _field(visit, "notes")
        notes = raw_notes.strip() or None if isinstance(raw_notes, str) else None
        prepared.append((visit_date, normalized_indicators, notes))

    prepared.sort(key=lambda item: item[0])
    return [
        NormalizedVisit(
            visit_date=visit_date,
            visit_index=index,
            indicators=indicators,
            notes=notes,
            visit_context=context.model_dump(exclude_none=True),
        )
        for index, (visit_date, indicators, notes) in enumerate(prepared, start=1)
    ]
