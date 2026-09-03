"""Report readiness derived from a saved case and the active model release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.schemas.operator_case_workspace import (
    OperatorCaseReadinessBlocker,
    OperatorCaseReportReadiness,
)
from app.services.disease_catalog import DiseaseCatalogError, require_enabled_case_disease
from app.services.longitudinal_model_registry import load_active_model_registry
from app.services.longitudinal_release_set import load_disease_release_set
from app.services.longitudinal_task_routing import route_outcome_task
from app.services.model_paths import MODEL_DIR
from app.services.operator_case_validation import (
    OperatorCaseValidationError,
    normalize_operator_timeline,
    validate_operator_case_profile,
)
from app.services.operator_indicator_catalog import IndicatorCatalogUnavailableError


class OperatorCaseReadinessError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_active_minimum_visits(
    dataset: str,
    registry_root: Path | str = MODEL_DIR,
) -> int:
    root = Path(registry_root).resolve()
    release = load_disease_release_set(dataset, root)
    manifest_path = (root / "datasets" / release.data_release_id / "manifest.json").resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise OperatorCaseReadinessError(
            "dataset_manifest_path_invalid",
            "活动模型数据清单路径无效",
        ) from exc
    if not manifest_path.is_file():
        raise OperatorCaseReadinessError(
            "dataset_manifest_missing",
            "活动模型数据清单不存在",
        )
    if _sha256(manifest_path) != release.dataset_manifest_sha256:
        raise OperatorCaseReadinessError(
            "dataset_manifest_hash_mismatch",
            "活动模型数据清单完整性校验失败",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        minimum_visits = manifest["minimum_visits"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise OperatorCaseReadinessError(
            "dataset_manifest_invalid",
            "活动模型数据清单无效",
        ) from exc
    if isinstance(minimum_visits, bool) or not isinstance(minimum_visits, int) or minimum_visits < 1:
        raise OperatorCaseReadinessError(
            "dataset_manifest_invalid",
            "活动模型数据清单中的 minimum_visits 无效",
        )
    return minimum_visits


def _blocker(code: str, message: str) -> OperatorCaseReadinessBlocker:
    return OperatorCaseReadinessBlocker(code=code, message=message)


def evaluate_operator_case_readiness(
    case: Any,
    registry_root: Path | str = MODEL_DIR,
) -> OperatorCaseReportReadiness:
    blockers: list[OperatorCaseReadinessBlocker] = []
    disease = getattr(case, "disease", None)
    disease_code = getattr(disease, "code", "")

    status_ready = getattr(case, "status", None) == "active"
    if not status_ready:
        blockers.append(_blocker("case_archived", "病例已归档，不能生成新报告"))

    disease_ready = True
    try:
        require_enabled_case_disease(case)
    except DiseaseCatalogError:
        disease_ready = False
        blockers.append(_blocker("disease_disabled", "疾病已停用或未开放，病例当前只读"))

    profile_ready = True
    normalized_stage = None
    try:
        normalized_stage = validate_operator_case_profile(
            disease_code,
            getattr(case, "age", None),
            getattr(case, "sex", None),
            getattr(case, "baseline_stage", None),
        )
    except OperatorCaseValidationError as exc:
        profile_ready = False
        blockers.append(_blocker("case_incomplete", exc.message))

    raw_visits = list(getattr(case, "visits", ()) or ())
    visit_count = len(raw_visits)
    timeline_valid = True
    try:
        normalize_operator_timeline(disease_code, raw_visits)
    except OperatorCaseValidationError as exc:
        timeline_valid = False
        blockers.append(_blocker("invalid_timeline", exc.message))
    except IndicatorCatalogUnavailableError:
        timeline_valid = False
        blockers.append(_blocker("indicator_catalog_unavailable", "指标目录暂时不可用"))

    minimum_visits: int | None = None
    model_metadata_ready = True
    try:
        minimum_visits = load_active_minimum_visits(disease_code, registry_root)
    except Exception:
        model_metadata_ready = False
        blockers.append(_blocker("model_unavailable", "活动模型或数据清单暂时不可用"))

    enough_visits = bool(
        timeline_valid
        and minimum_visits is not None
        and visit_count >= minimum_visits
    )
    if timeline_valid and minimum_visits is not None and not enough_visits:
        blockers.append(
            _blocker(
                "insufficient_visits",
                f"当前有 {visit_count} 次有效访视，活动模型至少需要 {minimum_visits} 次",
            )
        )

    task_applicable = profile_ready
    if normalized_stage is not None:
        route = route_outcome_task(disease_code, normalized_stage)
        task_applicable = route.routing_status == "selected"
        if not task_applicable:
            blockers.append(
                _blocker(
                    "prediction_not_applicable",
                    "当前确定阶段没有适用的纵向结局预测任务",
                )
            )

    runtime_ready = model_metadata_ready and task_applicable
    if runtime_ready:
        try:
            load_active_model_registry(disease_code, registry_root=registry_root)
        except Exception:
            runtime_ready = False
            blockers.append(_blocker("model_unavailable", "活动模型暂时不可用"))

    case_ready = status_ready and disease_ready and profile_ready
    timeline_ready = timeline_valid and enough_visits
    model_ready = model_metadata_ready and runtime_ready
    ready = case_ready and timeline_ready and model_ready and not blockers
    return OperatorCaseReportReadiness(
        ready=ready,
        case_ready=case_ready,
        timeline_ready=timeline_ready,
        model_ready=model_ready,
        visit_count=visit_count,
        minimum_visits=minimum_visits,
        blockers=blockers,
    )
