"""Explicit baseline-stage normalization and longitudinal outcome routing."""

from __future__ import annotations

import re
from typing import Any

from app.schemas.longitudinal_model_registry import BaselineStageRoute


FATTY_LIVER_ALIASES = {
    "pre_cirrhosis": "pre_cirrhosis",
    "fatty_liver": "pre_cirrhosis",
    "脂肪肝": "pre_cirrhosis",
    "未肝硬化": "pre_cirrhosis",
    "非肝硬化": "pre_cirrhosis",
    "cirrhosis": "cirrhosis",
    "肝硬化": "cirrhosis",
    "suspected_cirrhosis": "suspected_cirrhosis",
    "疑似肝硬化": "suspected_cirrhosis",
    "hcc": "hcc",
    "肝癌": "hcc",
    "肝细胞癌": "hcc",
}
AD_ALIASES = {
    "normal": "normal",
    "认知正常": "normal",
    "mci": "mci",
    "轻度认知障碍": "mci",
    "pre_dementia": "pre_dementia",
    "痴呆前": "pre_dementia",
    "痴呆前状态": "pre_dementia",
    "dementia": "dementia",
    "痴呆": "dementia",
}

ALIASES = {"fatty_liver": FATTY_LIVER_ALIASES, "ad": AD_ALIASES}
OTHER_DATASET_ALIASES = {
    "fatty_liver": AD_ALIASES,
    "ad": FATTY_LIVER_ALIASES,
}
SEPARATOR = re.compile(r"[/|,，;；]")


def _key(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().lower())


def _not_estimable(
    dataset: str,
    reason_code: str,
    normalized_stage: str | None = None,
) -> BaselineStageRoute:
    return BaselineStageRoute(
        dataset=dataset,
        routing_status="not_estimable",
        normalized_stage=normalized_stage,
        task=None,
        reason_code=reason_code,
    )


def normalize_baseline_stage(dataset: str, raw_stage: Any) -> BaselineStageRoute:
    if dataset not in ALIASES:
        return _not_estimable(dataset, "dataset_unsupported")
    if raw_stage is None:
        return _not_estimable(dataset, "baseline_stage_missing")
    if not isinstance(raw_stage, str):
        return _not_estimable(dataset, "baseline_stage_unknown")
    stripped = raw_stage.strip()
    if not stripped:
        return _not_estimable(dataset, "baseline_stage_missing")

    parts = [part for part in SEPARATOR.split(stripped) if part.strip()]
    aliases = ALIASES[dataset]
    normalized = [aliases.get(_key(part)) for part in parts]
    known = {item for item in normalized if item is not None}
    if len(known) > 1:
        return _not_estimable(dataset, "baseline_stage_conflict")
    if len(parts) > 1 and (not known or any(item is None for item in normalized)):
        return _not_estimable(dataset, "baseline_stage_unknown")
    if not known:
        other_aliases = OTHER_DATASET_ALIASES[dataset]
        if any(_key(part) in other_aliases for part in parts):
            return _not_estimable(dataset, "baseline_stage_disease_conflict")
        return _not_estimable(dataset, "baseline_stage_unknown")
    return _not_estimable(dataset, "baseline_stage_normalized", known.pop())


def route_outcome_task(dataset: str, raw_stage: Any) -> BaselineStageRoute:
    normalized = normalize_baseline_stage(dataset, raw_stage)
    if normalized.normalized_stage is None:
        return normalized
    stage = normalized.normalized_stage

    if dataset == "fatty_liver":
        if stage == "pre_cirrhosis":
            task = "fatty_liver.pre_cirrhosis_to_progression"
        elif stage == "cirrhosis":
            task = "fatty_liver.cirrhosis_to_hcc"
        elif stage == "suspected_cirrhosis":
            return _not_estimable(dataset, "baseline_stage_uncertain", stage)
        elif stage == "hcc":
            return _not_estimable(dataset, "task_not_applicable_terminal_stage", stage)
        else:
            return _not_estimable(dataset, "baseline_stage_disease_conflict")
    elif dataset == "ad":
        if stage in {"normal", "mci", "pre_dementia"}:
            task = "ad.pre_dementia_to_dementia"
        elif stage == "dementia":
            return _not_estimable(dataset, "task_not_applicable_terminal_stage", stage)
        else:
            return _not_estimable(dataset, "baseline_stage_disease_conflict")
    else:
        return _not_estimable(dataset, "dataset_unsupported")

    return BaselineStageRoute(
        dataset=dataset,
        routing_status="selected",
        normalized_stage=stage,
        task=task,
        reason_code="task_selected",
    )
