"""Read-only checks for longitudinal report readiness."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import text

from app.schemas.longitudinal_readiness import (
    ArtifactReadiness,
    CapabilityReadiness,
    DataReadiness,
    DiseaseReadiness,
    EnvironmentReadiness,
    LongitudinalReadinessReport,
    ModelReadiness,
    ReadinessReason,
    ReportContractReadiness,
    StandardReadiness,
    status_from_reasons,
)
from app.services.disease_progression import (
    AD_ADAPTER,
    FATTY_LIVER_ADAPTER,
    DiseaseProgressionAdapter,
)
from app.services.longitudinal_features import build_prefixes
from scripts.check_model_artifacts import sha256_file


CORE_DISEASES = (FATTY_LIVER_ADAPTER, AD_ADAPTER)
REFERENCE_DATASET_ALIASES = {
    "fatty_liver": ("longitudinal_300",),
    "ad": ("ad_longitudinal_300",),
}
OUTCOME_METADATA_FIELDS = frozenset(
    {
        "dataset",
        "disease",
        "target",
        "horizon_days",
        "feature_names",
        "feature_version",
        "model_name",
        "model_version",
        "training_dataset_version",
        "sklearn_version",
        "trained_at",
        "artifact_sha256",
        "calibration_status",
    }
)
REQUIRED_CAPABILITIES = (
    "case_identity",
    "input_scope",
    "data_quality_explanation",
    "observed_longitudinal_changes",
    "outcome_365d",
    "reference_standard_interpretation",
    "key_progression_signals",
    "evidence_sources",
    "limitations",
    "manual_review_items",
    "persistence_and_history",
    "pdf_delivery",
)
OPTIONAL_CAPABILITIES = (
    "stage_projection",
    "next_followup_trend_model",
    "calibrated_probability",
)
CURRENT_IMPLEMENTED_REQUIRED = frozenset(
    {
        "case_identity",
        "input_scope",
        "observed_longitudinal_changes",
        "outcome_365d",
        "reference_standard_interpretation",
        "evidence_sources",
        "limitations",
        "manual_review_items",
        "persistence_and_history",
        "pdf_delivery",
    }
)
TASK_ORDER = {
    task: index
    for index, task in enumerate(
        (
            "P0-01",
            "P0-02",
            "P0-03",
            "P0-04",
            "P0-05",
            "P0-06",
            "P0-07",
            "P1-01",
            "P1-02",
            "P1-03",
            "P1-04",
            "P1-05",
            "P2-01",
            "P2-02",
            "P2-03",
            "P2-04",
        )
    )
}


def _reason(
    code: str,
    message: str,
    severity: str,
    next_task: str,
    **details: object,
) -> ReadinessReason:
    return ReadinessReason(
        code=code,
        message=message,
        severity=severity,
        next_task=next_task,
        details=details,
    )


def aggregate_reference_data(
    rows: list[dict[str, object]],
    adapter: DiseaseProgressionAdapter,
) -> tuple[DataReadiness, list[ReadinessReason]]:
    patients: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        raw_metadata = row.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        source = str(metadata.get("source_dataset") or "unknown")
        label = str(row.get("patient_label") or "")
        patient = patients.setdefault(
            (source, label),
            {
                "visits": [],
                "case_metadata": metadata,
                "provenance": metadata.get("is_synthetic"),
            },
        )
        patient["visits"].append(
            {
                "visit_date": metadata.get("visit_date"),
                "indicators": row.get("indicators") or [],
            }
        )

    positive = negative = unknown = all_prefixes = visit_count = 0
    real = synthetic = provenance_unknown = 0
    for patient in patients.values():
        visits = [visit for visit in patient["visits"] if visit.get("visit_date")]
        visit_count += len(visits)
        provenance = patient.get("provenance")
        if provenance is True:
            synthetic += 1
        elif provenance is False:
            real += 1
        else:
            provenance_unknown += 1
        for prefix in build_prefixes(visits, adapter.minimum_visits):
            all_prefixes += 1
            label = adapter.outcome_label(
                patient,
                date.fromisoformat(prefix["as_of"]),
                timedelta(days=365),
            )
            if label == 1:
                positive += 1
            elif label == 0:
                negative += 1
            else:
                unknown += 1

    reasons: list[ReadinessReason] = []
    if not patients or visit_count == 0:
        reasons.append(
            _reason(
                "reference_data_missing",
                "缺少参考患者或纵向访视",
                "blocked",
                "P0-01",
            )
        )
    elif positive + negative == 0:
        reasons.append(
            _reason(
                "estimable_labels_missing",
                "没有可估计的未来365天结局标签",
                "blocked",
                "P0-03",
            )
        )
    elif positive == 0 or negative == 0:
        reasons.append(
            _reason(
                "label_class_missing",
                "可估计标签没有同时包含阳性和阴性",
                "blocked",
                "P0-03",
            )
        )

    data = DataReadiness(
        status="blocked" if reasons else "available",
        patient_count=len(patients),
        visit_count=visit_count,
        all_prefix_count=all_prefixes,
        estimable_prefix_count=positive + negative,
        positive_count=positive,
        negative_count=negative,
        unknown_count=unknown,
        source_datasets=sorted({source for source, _ in patients}),
        real_patient_count=real,
        synthetic_patient_count=synthetic,
        unknown_provenance_patient_count=provenance_unknown,
    )
    return data, reasons


def assess_standard(
    row: dict[str, object] | None,
) -> tuple[StandardReadiness, list[ReadinessReason]]:
    values = row or {}
    approved = values.get("version_status") == "approved"
    calculable = int(values.get("calculable_rule_count") or 0)
    reasons: list[ReadinessReason] = []
    if not approved:
        reasons.append(
            _reason(
                "approved_standard_missing",
                "没有当前已批准的参考标准",
                "blocked",
                "P0-02",
            )
        )
    elif calculable == 0:
        reasons.append(
            _reason(
                "calculable_standard_rules_missing",
                "当前标准没有可计算的正式规则",
                "blocked",
                "P0-02",
            )
        )
    return (
        StandardReadiness(
            status="blocked" if reasons else "available",
            standard_id=values.get("standard_id"),
            current_version_id=values.get("current_version_id"),
            version_label=values.get("version_label"),
            version_status=values.get("version_status"),
            content_hash=values.get("content_hash"),
            rule_count=int(values.get("rule_count") or 0),
            calculable_rule_count=calculable,
        ),
        reasons,
    )


def load_database_snapshot(connection) -> dict[str, object]:
    """Read longitudinal readiness inputs inside a read-only transaction."""
    connection.execute(text("SET TRANSACTION READ ONLY"))
    server_version = connection.execute(text("SHOW server_version")).scalar_one_or_none()
    alembic_revision = connection.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar_one_or_none()
    diseases = connection.execute(
        text("SELECT id, name FROM diseases ORDER BY id")
    ).mappings().all()
    case_rows = connection.execute(
        text(
            "SELECT cr.disease_id, d.name AS disease_name, cr.patient_label, "
            "cr.indicators, cr.metadata "
            "FROM case_records cr JOIN diseases d ON d.id = cr.disease_id "
            "ORDER BY cr.disease_id, cr.patient_label, cr.id"
        )
    ).mappings().all()
    standard_rows = connection.execute(
        text(
            "SELECT d.id AS disease_id, d.name AS disease_name, "
            "rs.id AS standard_id, rs.current_version_id, "
            "rsv.version_label, rsv.status AS version_status, rsv.content_hash, "
            "COUNT(sr.id) AS rule_count, "
            "COUNT(sr.id) FILTER "
            "(WHERE sr.machine_actionability = 'calculable') "
            "AS calculable_rule_count "
            "FROM diseases d "
            "LEFT JOIN reference_standards rs ON rs.disease_id = d.id "
            "LEFT JOIN reference_standard_versions rsv "
            "ON rsv.id = rs.current_version_id "
            "LEFT JOIN standard_rules sr ON sr.version_id = rsv.id "
            "GROUP BY d.id, d.name, rs.id, rs.current_version_id, "
            "rsv.version_label, rsv.status, rsv.content_hash "
            "ORDER BY d.id"
        )
    ).mappings().all()
    column_rows = connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name IN "
            "('ai_reports', 'operator_cases', 'operator_case_visits') "
            "ORDER BY table_name, column_name"
        )
    ).mappings().all()
    table_columns: dict[str, set[str]] = defaultdict(set)
    for row in column_rows:
        table_columns[str(row["table_name"])].add(str(row["column_name"]))
    return {
        "server_version": server_version,
        "alembic_revision": alembic_revision,
        "diseases": [dict(row) for row in diseases],
        "case_rows": [dict(row) for row in case_rows],
        "standard_rows": [dict(row) for row in standard_rows],
        "table_columns": dict(table_columns),
    }


def _outcome_issue_reason(issues: list[str]) -> ReadinessReason:
    return _reason(
        "outcome_model_incompatible",
        "未来365天结局模型与契约不兼容",
        "blocked",
        "P0-04",
        issues=issues,
    )


def check_outcome_artifact(
    dataset: str,
    model_dir: Path,
) -> tuple[ArtifactReadiness, list[ReadinessReason]]:
    directory = Path(model_dir)
    stem = f"{dataset}_longitudinal_outcome_365d"
    model_path = directory / f"{stem}.joblib"
    meta_path = directory / f"{stem}.meta.json"
    model_exists = model_path.is_file()
    meta_exists = meta_path.is_file()
    base = {
        "artifact_type": "outcome",
        "model_file": model_path.name,
        "metadata_file": meta_path.name,
    }
    if not model_exists and not meta_exists:
        return (
            ArtifactReadiness(status="missing", **base),
            [
                _reason(
                    "outcome_model_missing",
                    "缺少未来365天结局模型",
                    "blocked",
                    "P0-04",
                )
            ],
        )
    if model_exists != meta_exists:
        issues = [
            "metadata_file_missing" if model_exists else "model_file_missing"
        ]
        return (
            ArtifactReadiness(status="incompatible", issues=issues, **base),
            [_outcome_issue_reason(issues)],
        )

    issues: list[str] = []
    metadata: dict[str, object] = {}
    try:
        raw_metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(raw_metadata, dict):
            issues.append("metadata_not_object")
        else:
            metadata = raw_metadata
    except (OSError, UnicodeError, json.JSONDecodeError):
        issues.append("metadata_unreadable")

    if metadata:
        for field in sorted(OUTCOME_METADATA_FIELDS - set(metadata)):
            issues.append(f"missing_metadata:{field}")
        adapter = next((item for item in CORE_DISEASES if item.dataset == dataset), None)
        expected_disease = adapter.disease_name if adapter else None
        if metadata.get("dataset") != dataset:
            issues.append("dataset_mismatch")
        if metadata.get("disease") != expected_disease:
            issues.append("disease_mismatch")
        if metadata.get("target") != "outcome_365d":
            issues.append("target_mismatch")
        if metadata.get("horizon_days") != 365:
            issues.append("horizon_mismatch")
        feature_names = metadata.get("feature_names")
        if not (
            isinstance(feature_names, list)
            and feature_names
            and all(isinstance(item, str) and item for item in feature_names)
        ):
            issues.append("feature_names_invalid")
        if not isinstance(metadata.get("feature_version"), str) or not str(
            metadata.get("feature_version") or ""
        ).strip():
            issues.append("feature_version_invalid")

    if not issues:
        try:
            actual_hash = sha256_file(model_path)
        except OSError:
            issues.append("artifact_unreadable")
        else:
            if metadata.get("artifact_sha256") != actual_hash:
                issues.append("artifact_sha256_mismatch")

    model = None
    if not issues:
        try:
            model = joblib.load(model_path)
        except Exception:
            issues.append("artifact_load_failed")
    if model is not None and not callable(getattr(model, "predict_proba", None)):
        issues.append("predict_proba_missing")

    if issues:
        stable_issues = sorted(dict.fromkeys(issues))
        return (
            ArtifactReadiness(
                status="incompatible",
                metadata=metadata,
                issues=stable_issues,
                **base,
            ),
            [_outcome_issue_reason(stable_issues)],
        )
    return (
        ArtifactReadiness(status="available", metadata=metadata, **base),
        [],
    )


def check_optional_artifacts(
    adapter: DiseaseProgressionAdapter,
    model_dir: Path,
) -> tuple[ArtifactReadiness, list[ArtifactReadiness], list[ReadinessReason]]:
    directory = Path(model_dir)
    stage = ArtifactReadiness(status="not_configured", artifact_type="stage")
    reasons = [
        _reason(
            "stage_model_missing",
            "阶段模型尚未配置",
            "degraded",
            "P2-01",
        )
    ]
    trends: list[ArtifactReadiness] = []
    missing_indicators: list[str] = []
    incompatible_indicators: list[str] = []
    for indicator in adapter.key_indicators:
        model_path = directory / f"{adapter.dataset}_trend_{indicator}.joblib"
        meta_path = directory / f"{adapter.dataset}_trend_{indicator}.meta.json"
        model_exists = model_path.is_file()
        meta_exists = meta_path.is_file()
        issues: list[str] = []
        metadata: dict[str, object] = {}
        if not model_exists and not meta_exists:
            status = "missing"
            missing_indicators.append(indicator)
        elif model_exists != meta_exists:
            status = "incompatible"
            issues.append(
                "metadata_file_missing" if model_exists else "model_file_missing"
            )
            incompatible_indicators.append(indicator)
        else:
            try:
                raw_metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(raw_metadata, dict):
                    metadata = raw_metadata
                else:
                    issues.append("metadata_not_object")
            except (OSError, UnicodeError, json.JSONDecodeError):
                issues.append("metadata_unreadable")
            if not issues:
                try:
                    joblib.load(model_path)
                except Exception:
                    issues.append("artifact_load_failed")
            status = "incompatible" if issues else "available"
            if issues:
                incompatible_indicators.append(indicator)
        trends.append(
            ArtifactReadiness(
                status=status,
                artifact_type="trend",
                indicator=indicator,
                model_file=model_path.name,
                metadata_file=meta_path.name,
                metadata=metadata,
                issues=sorted(issues),
            )
        )
    unavailable = missing_indicators + incompatible_indicators
    if unavailable:
        reasons.append(
            _reason(
                "trend_models_missing",
                "部分或全部下一次随访趋势模型不可用",
                "degraded",
                "P2-02",
                missing_indicators=sorted(missing_indicators),
                incompatible_indicators=sorted(incompatible_indicators),
            )
        )
    return stage, trends, reasons


def assess_report_contract(
    *,
    table_columns: dict[str, set[str]],
    data: DataReadiness,
    standard: StandardReadiness,
    outcome: ArtifactReadiness,
    stage: ArtifactReadiness,
    trends: list[ArtifactReadiness],
    implemented_required: set[str] | None = None,
) -> tuple[ReportContractReadiness, list[ReadinessReason], list[str]]:
    implemented = (
        set(CURRENT_IMPLEMENTED_REQUIRED)
        if implemented_required is None
        else set(implemented_required)
    )
    report_columns = table_columns.get("ai_reports", set())
    case_columns = table_columns.get("operator_cases", set())
    visit_columns = table_columns.get("operator_case_visits", set())
    storage_ready = {
        "input_snapshot",
        "prediction_result",
        "content",
        "status",
        "operator_case_id",
    }.issubset(report_columns)
    identity_ready = {"patient_label", "disease_id"}.issubset(case_columns)
    visits_ready = {"case_id", "visit_date", "indicators"}.issubset(
        visit_columns
    )
    dependency_ready = {
        "case_identity": identity_ready,
        "input_scope": identity_ready and visits_ready and "input_snapshot" in report_columns,
        "data_quality_explanation": data.status == "available",
        "observed_longitudinal_changes": data.status == "available" and visits_ready,
        "outcome_365d": outcome.status == "available",
        "reference_standard_interpretation": standard.status == "available",
        "key_progression_signals": data.status == "available",
        "evidence_sources": "sources" in report_columns,
        "limitations": "content" in report_columns,
        "manual_review_items": "content" in report_columns,
        "persistence_and_history": storage_ready,
        "pdf_delivery": storage_ready,
    }
    messages = {
        "case_identity": "病例身份字段可追溯",
        "input_scope": "输入快照和访视范围可保存",
        "data_quality_explanation": "数据质量问题可结构化说明",
        "observed_longitudinal_changes": "可计算已观察纵向变化",
        "outcome_365d": "未来365天结局模型可用",
        "reference_standard_interpretation": "参考标准可用于结构化解释",
        "key_progression_signals": "关键进展信号具有结构化解释",
        "evidence_sources": "证据来源可持久化",
        "limitations": "局限性可进入持久化报告",
        "manual_review_items": "人工复核事项可进入持久化报告",
        "persistence_and_history": "报告输入、结果和正文可持久化查看",
        "pdf_delivery": "完成报告具备 PDF 交付链路",
    }
    capabilities: list[CapabilityReadiness] = []
    available: list[str] = []
    missing_required: list[str] = []
    for key in REQUIRED_CAPABILITIES:
        is_available = dependency_ready[key] and key in implemented
        if is_available:
            available.append(key)
        else:
            missing_required.append(key)
        capabilities.append(
            CapabilityReadiness(
                key=key,
                required=True,
                status="available" if is_available else "blocked",
                message=messages[key],
                next_task=None if is_available else "P0-07",
            )
        )

    stage_available = stage.status == "available"
    trend_available = bool(trends) and all(
        item.status == "available" for item in trends
    )
    calibration_available = (
        outcome.status == "available"
        and outcome.metadata.get("calibration_status")
        not in (None, "", "not_calibrated")
    )
    optional_rows = (
        (
            "stage_projection",
            stage_available,
            "疾病阶段模型可用",
            "P2-01",
        ),
        (
            "next_followup_trend_model",
            trend_available,
            "下一次随访趋势模型可用",
            "P2-02",
        ),
        (
            "calibrated_probability",
            calibration_available,
            "模型分数已经校准",
            "P2-03",
        ),
    )
    for key, is_available, message, next_task in optional_rows:
        if is_available:
            available.append(key)
        capabilities.append(
            CapabilityReadiness(
                key=key,
                required=False,
                status="available" if is_available else "degraded",
                message=message,
                next_task=None if is_available else next_task,
            )
        )

    reasons: list[ReadinessReason] = []
    if missing_required:
        reasons.append(
            _reason(
                "report_contract_invalid",
                "完整报告必需能力尚未全部具备",
                "blocked",
                "P0-07",
                missing_capabilities=sorted(missing_required),
            )
        )
    if outcome.status == "available" and not calibration_available:
        reasons.append(
            _reason(
                "model_not_calibrated",
                "未来365天结局模型分数尚未校准",
                "degraded",
                "P2-03",
            )
        )
    status = "blocked" if missing_required else (
        "degraded"
        if any(item.status == "degraded" for item in capabilities)
        else "available"
    )
    return (
        ReportContractReadiness(status=status, capabilities=capabilities),
        reasons,
        available,
    )


def _ordered_reasons(reasons: list[ReadinessReason]) -> list[ReadinessReason]:
    unique: dict[tuple[str, str], ReadinessReason] = {}
    for reason in reasons:
        unique.setdefault((reason.code, reason.next_task), reason)
    return sorted(
        unique.values(),
        key=lambda item: (
            TASK_ORDER.get(item.next_task, len(TASK_ORDER)),
            item.next_task,
            item.code,
        ),
    )


def build_readiness_report(
    snapshot: dict[str, object],
    *,
    model_dir: Path,
    code_heads: set[str],
    generated_at: datetime | str | None = None,
) -> LongitudinalReadinessReport:
    diseases = {
        str(row.get("name")): row
        for row in snapshot.get("diseases", [])
        if isinstance(row, dict)
    }
    case_rows = [
        row for row in snapshot.get("case_rows", []) if isinstance(row, dict)
    ]
    standard_rows = [
        row
        for row in snapshot.get("standard_rows", [])
        if isinstance(row, dict)
    ]
    table_columns = {
        str(table): set(columns)
        for table, columns in dict(snapshot.get("table_columns", {})).items()
    }
    disease_results: dict[str, DiseaseReadiness] = {}
    for adapter in CORE_DISEASES:
        disease_row = diseases.get(adapter.disease_name)
        reasons: list[ReadinessReason] = []
        disease_id = disease_row.get("id") if disease_row else None
        if disease_row is None:
            reasons.append(
                _reason(
                    "disease_not_found",
                    f"数据库中缺少疾病：{adapter.disease_name}",
                    "blocked",
                    "P0-01",
                )
            )
        rows = [
            row for row in case_rows if row.get("disease_id") == disease_id
        ]
        data, data_reasons = aggregate_reference_data(rows, adapter)
        reasons.extend(data_reasons)
        standard_row = next(
            (
                row
                for row in standard_rows
                if row.get("disease_id") == disease_id
            ),
            None,
        )
        standard, standard_reasons = assess_standard(standard_row)
        reasons.extend(standard_reasons)
        outcome, outcome_reasons = check_outcome_artifact(
            adapter.dataset, Path(model_dir)
        )
        reasons.extend(outcome_reasons)
        stage, trends, optional_reasons = check_optional_artifacts(
            adapter, Path(model_dir)
        )
        reasons.extend(optional_reasons)
        contract, contract_reasons, available = assess_report_contract(
            table_columns=table_columns,
            data=data,
            standard=standard,
            outcome=outcome,
            stage=stage,
            trends=trends,
        )
        reasons.extend(contract_reasons)
        ordered = _ordered_reasons(reasons)
        disease_results[adapter.dataset] = DiseaseReadiness(
            dataset=adapter.dataset,
            disease_name=adapter.disease_name,
            status=status_from_reasons(ordered),
            data=data,
            standard=standard,
            models=ModelReadiness(
                outcome=outcome,
                stage=stage,
                trends=trends,
            ),
            report_contract=contract,
            available_capabilities=available,
            reasons=ordered,
            next_tasks=list(
                dict.fromkeys(reason.next_task for reason in ordered)
            ),
        )

    severity = {"ready": 0, "degraded": 1, "blocked": 2}
    overall_status = max(
        (item.status for item in disease_results.values()),
        key=severity.__getitem__,
    )
    revision = snapshot.get("alembic_revision")
    revision_matches = revision in code_heads and len(code_heads) == 1
    return LongitudinalReadinessReport(
        generated_at=generated_at or datetime.now(timezone.utc),
        overall_status=overall_status,
        environment=EnvironmentReadiness(
            database_check="available",
            alembic_revision=str(revision) if revision is not None else None,
            code_heads=sorted(code_heads),
            revision_matches=revision_matches,
        ),
        diseases=disease_results,
    )


def collect_longitudinal_readiness(
    connection,
    *,
    model_dir: Path,
    code_heads: set[str],
    generated_at: datetime | str | None = None,
) -> LongitudinalReadinessReport:
    return build_readiness_report(
        load_database_snapshot(connection),
        model_dir=model_dir,
        code_heads=code_heads,
        generated_at=generated_at,
    )
