"""Read-only checks for longitudinal report readiness."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import text

from app.schemas.longitudinal_readiness import (
    ArtifactReadiness,
    DataReadiness,
    ReadinessReason,
    StandardReadiness,
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
