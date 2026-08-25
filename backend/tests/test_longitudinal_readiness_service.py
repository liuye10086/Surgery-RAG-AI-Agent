import json

import joblib

from scripts.check_model_artifacts import sha256_file

from app.schemas.longitudinal_readiness import (
    ArtifactReadiness,
    DataReadiness,
    StandardReadiness,
)
from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_readiness import (
    REQUIRED_CAPABILITIES,
    aggregate_reference_data,
    assess_report_contract,
    assess_standard,
    build_readiness_report,
    check_optional_artifacts,
    check_outcome_artifact,
    collect_longitudinal_readiness,
    load_database_snapshot,
)


def _row(
    patient,
    visit_date,
    *,
    final_stage,
    event_dates,
    synthetic=None,
    source="longitudinal_300",
):
    metadata = {
        "source_dataset": source,
        "visit_date": visit_date,
        "final_stage": final_stage,
        "event_dates": event_dates,
    }
    if synthetic is not None:
        metadata["is_synthetic"] = synthetic
    return {
        "patient_label": patient,
        "indicators": [{"name": "ALT", "value": 10}],
        "metadata": metadata,
    }


def test_reference_data_groups_patients_and_preserves_unknown_labels():
    rows = [
        _row(
            "P1",
            "2024-01-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=False,
        ),
        _row(
            "P1",
            "2024-06-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=False,
        ),
        _row(
            "P2",
            "2024-01-01",
            final_stage="cirrhosis",
            event_dates={},
            synthetic=True,
        ),
        _row(
            "P2",
            "2024-06-01",
            final_stage="cirrhosis",
            event_dates={},
            synthetic=True,
        ),
    ]
    data, reasons = aggregate_reference_data(rows, FATTY_LIVER_ADAPTER)
    assert data.patient_count == 2
    assert data.visit_count == 4
    assert data.all_prefix_count == 2
    assert data.negative_count == 1
    assert data.positive_count == 0
    assert data.unknown_count == 1
    assert data.real_patient_count == 1
    assert data.synthetic_patient_count == 1
    assert {reason.code for reason in reasons} == {"label_class_missing"}


def test_reference_data_does_not_guess_provenance_from_patient_number():
    rows = [
        _row(
            "P999",
            "2024-01-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=None,
        ),
        _row(
            "P999",
            "2024-06-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=None,
        ),
    ]
    data, _ = aggregate_reference_data(rows, FATTY_LIVER_ADAPTER)
    assert data.synthetic_patient_count == 0
    assert data.unknown_provenance_patient_count == 1


def test_ad_uses_ad_event_semantics_for_positive_prefix():
    rows = [
        _row(
            "A1",
            "2024-01-01",
            final_stage="dementia",
            event_dates={"dementia_date": "2024-12-01"},
            source="ad_longitudinal_300",
        ),
        _row(
            "A1",
            "2024-02-01",
            final_stage="dementia",
            event_dates={"dementia_date": "2024-12-01"},
            source="ad_longitudinal_300",
        ),
    ]
    data, _ = aggregate_reference_data(rows, AD_ADAPTER)
    assert data.positive_count == 1


def test_standard_requires_current_approved_version_and_calculable_rule():
    missing, missing_reasons = assess_standard(None)
    assert missing.status == "blocked"
    assert [reason.code for reason in missing_reasons] == [
        "approved_standard_missing"
    ]

    retired, retired_reasons = assess_standard(
        {
            "standard_id": 1,
            "current_version_id": 2,
            "version_status": "retired",
            "version_label": "v0.1",
            "content_hash": "abc",
            "rule_count": 0,
            "calculable_rule_count": 0,
        }
    )
    assert retired.status == "blocked"
    assert [reason.code for reason in retired_reasons] == [
        "approved_standard_missing"
    ]

    evidence_only, reasons = assess_standard(
        {
            "standard_id": 1,
            "current_version_id": 3,
            "version_status": "approved",
            "version_label": "v1",
            "content_hash": "def",
            "rule_count": 4,
            "calculable_rule_count": 0,
        }
    )
    assert evidence_only.status == "blocked"
    assert [reason.code for reason in reasons] == [
        "calculable_standard_rules_missing"
    ]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        self.statements.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            return _FakeResult([])
        if sql == "SHOW server_version":
            return _FakeResult(["18.1"])
        if "FROM alembic_version" in sql:
            return _FakeResult(["0010"])
        if (
            "FROM diseases" in sql
            and "case_records" not in sql
            and "reference_standards" not in sql
        ):
            return _FakeResult(
                [
                    {"id": 2, "name": "脂肪肝"},
                    {"id": 4, "name": "阿尔茨海默病"},
                ]
            )
        if "FROM case_records" in sql:
            return _FakeResult([])
        if "reference_standards" in sql:
            return _FakeResult([])
        if "information_schema.columns" in sql:
            return _FakeResult(
                [
                    {"table_name": "ai_reports", "column_name": "input_snapshot"},
                    {
                        "table_name": "ai_reports",
                        "column_name": "prediction_result",
                    },
                    {"table_name": "ai_reports", "column_name": "content"},
                    {"table_name": "ai_reports", "column_name": "status"},
                    {
                        "table_name": "ai_reports",
                        "column_name": "operator_case_id",
                    },
                    {
                        "table_name": "operator_cases",
                        "column_name": "patient_label",
                    },
                    {"table_name": "operator_cases", "column_name": "disease_id"},
                    {
                        "table_name": "operator_case_visits",
                        "column_name": "case_id",
                    },
                    {
                        "table_name": "operator_case_visits",
                        "column_name": "visit_date",
                    },
                    {
                        "table_name": "operator_case_visits",
                        "column_name": "indicators",
                    },
                ]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


def test_load_database_snapshot_starts_with_read_only_and_uses_only_selects():
    connection = _FakeConnection()
    snapshot = load_database_snapshot(connection)
    assert connection.statements[0] == "SET TRANSACTION READ ONLY"
    assert snapshot["alembic_revision"] == "0010"
    assert snapshot["server_version"] == "18.1"
    assert snapshot["table_columns"]["ai_reports"] == {
        "input_snapshot",
        "prediction_result",
        "content",
        "status",
        "operator_case_id",
    }
    for sql in connection.statements[1:]:
        assert sql.lstrip().upper().startswith(("SELECT", "SHOW"))


class _PredictProbaModel:
    def predict_proba(self, rows):
        raise AssertionError("readiness 检查不得执行患者预测")


def _write_outcome_artifact(tmp_path, *, metadata_updates=None):
    model_path = tmp_path / "fatty_liver_longitudinal_outcome_365d.joblib"
    meta_path = tmp_path / "fatty_liver_longitudinal_outcome_365d.meta.json"
    joblib.dump(_PredictProbaModel(), model_path)
    metadata = {
        "dataset": "fatty_liver",
        "disease": "脂肪肝",
        "target": "outcome_365d",
        "horizon_days": 365,
        "feature_names": ["alt.last"],
        "feature_version": "longitudinal_features.v1",
        "model_name": "GradientBoostingClassifier",
        "model_version": "test-v1",
        "training_dataset_version": "test-dataset-v1",
        "sklearn_version": "1.9.0",
        "trained_at": "2026-08-25T00:00:00Z",
        "artifact_sha256": sha256_file(model_path),
        "calibration_status": "not_calibrated",
    }
    metadata.update(metadata_updates or {})
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    return model_path, meta_path


def test_missing_outcome_artifact_maps_to_p0_04(tmp_path):
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "missing"
    assert [reason.code for reason in reasons] == ["outcome_model_missing"]
    assert reasons[0].next_task == "P0-04"


def test_outcome_artifact_rejects_missing_metadata_field(tmp_path):
    _, meta_path = _write_outcome_artifact(tmp_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata.pop("feature_version")
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "incompatible"
    assert [reason.code for reason in reasons] == [
        "outcome_model_incompatible"
    ]
    assert "missing_metadata:feature_version" in artifact.issues


def test_outcome_artifact_rejects_wrong_hash_without_loading(
    tmp_path, monkeypatch
):
    _write_outcome_artifact(
        tmp_path, metadata_updates={"artifact_sha256": "0" * 64}
    )
    monkeypatch.setattr(
        "app.services.longitudinal_readiness.joblib.load",
        lambda path: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "incompatible"
    assert artifact.issues == ["artifact_sha256_mismatch"]
    assert reasons[0].code == "outcome_model_incompatible"


def test_compatible_outcome_artifact_is_loaded_but_not_invoked(tmp_path):
    _write_outcome_artifact(tmp_path)
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "available"
    assert reasons == []
    assert artifact.metadata["model_version"] == "test-v1"


def test_legacy_progression_model_is_not_accepted_as_365_day_outcome(
    tmp_path,
):
    joblib.dump(
        _PredictProbaModel(), tmp_path / "fatty_liver_progression_model.joblib"
    )
    (tmp_path / "fatty_liver_progression_model.meta.json").write_text(
        "{}", encoding="utf-8"
    )
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "missing"
    assert reasons[0].code == "outcome_model_missing"


def test_stage_not_configured_and_missing_trends_are_degraded(tmp_path):
    stage, trends, reasons = check_optional_artifacts(
        FATTY_LIVER_ADAPTER, tmp_path
    )
    assert stage.status == "not_configured"
    assert {item.indicator for item in trends} == set(
        FATTY_LIVER_ADAPTER.key_indicators
    )
    assert all(item.status == "missing" for item in trends)
    assert {reason.code for reason in reasons} == {
        "stage_model_missing",
        "trend_models_missing",
    }
    assert all(reason.severity == "degraded" for reason in reasons)


def _complete_data():
    return DataReadiness(
        status="available",
        patient_count=2,
        visit_count=4,
        all_prefix_count=2,
        estimable_prefix_count=2,
        positive_count=1,
        negative_count=1,
        unknown_count=0,
        source_datasets=["longitudinal_300"],
        real_patient_count=2,
        synthetic_patient_count=0,
        unknown_provenance_patient_count=0,
    )


def _available_standard():
    return StandardReadiness(
        status="available",
        standard_id=1,
        current_version_id=2,
        version_label="v1",
        version_status="approved",
        content_hash="abc",
        rule_count=2,
        calculable_rule_count=1,
    )


def _artifact(artifact_type, status, *, indicator=None, metadata=None):
    return ArtifactReadiness(
        status=status,
        artifact_type=artifact_type,
        indicator=indicator,
        metadata=metadata or {},
    )


def _table_columns():
    return {
        "ai_reports": {
            "input_snapshot",
            "prediction_result",
            "content",
            "status",
            "operator_case_id",
            "sources",
        },
        "operator_cases": {
            "patient_label",
            "disease_id",
            "sex",
            "baseline_stage",
        },
        "operator_case_visits": {"case_id", "visit_date", "indicators"},
    }


def test_required_capability_failure_blocks_report_contract():
    contract, reasons, available = assess_report_contract(
        table_columns=_table_columns(),
        data=_complete_data(),
        standard=_available_standard(),
        outcome=_artifact(
            "outcome",
            "available",
            metadata={"calibration_status": "not_calibrated"},
        ),
        stage=_artifact("stage", "not_configured"),
        trends=[_artifact("trend", "missing", indicator="alt")],
        implemented_required={
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
        },
    )
    required = {
        item.key: item for item in contract.capabilities if item.required
    }
    assert required["case_identity"].status == "available"
    assert required["outcome_365d"].status == "available"
    assert contract.status == "blocked"
    assert [reason.code for reason in reasons] == ["report_contract_invalid"]
    assert set(reasons[0].details["missing_capabilities"]) == {
        "data_quality_explanation",
        "key_progression_signals",
    }
    assert "case_identity" in available


def test_optional_stage_and_trend_capabilities_do_not_block_required_contract():
    contract, reasons, _ = assess_report_contract(
        table_columns=_table_columns(),
        data=_complete_data(),
        standard=_available_standard(),
        outcome=_artifact(
            "outcome",
            "available",
            metadata={"calibration_status": "not_calibrated"},
        ),
        stage=_artifact("stage", "not_configured"),
        trends=[_artifact("trend", "missing", indicator="alt")],
        implemented_required=set(REQUIRED_CAPABILITIES),
    )
    assert contract.status == "degraded"
    assert reasons == []
    optional = {
        item.key: item for item in contract.capabilities if not item.required
    }
    assert optional["stage_projection"].status == "degraded"
    assert optional["next_followup_trend_model"].status == "degraded"


def _snapshot_fixture():
    return {
        "server_version": "18.1",
        "alembic_revision": "0010",
        "diseases": [
            {"id": 2, "name": "脂肪肝"},
            {"id": 4, "name": "阿尔茨海默病"},
        ],
        "case_rows": [],
        "standard_rows": [],
        "table_columns": _table_columns(),
    }


def test_build_report_keeps_diseases_separate_and_aggregates_worst_status(
    tmp_path,
):
    report = build_readiness_report(
        _snapshot_fixture(), model_dir=tmp_path, code_heads={"0010"}
    )
    assert set(report.diseases) == {"fatty_liver", "ad"}
    assert report.diseases["fatty_liver"].disease_name == "脂肪肝"
    assert report.diseases["ad"].disease_name == "阿尔茨海默病"
    assert report.overall_status == "blocked"
    assert "P0-02" in report.diseases["fatty_liver"].next_tasks
    assert "P0-04" in report.diseases["ad"].next_tasks


def test_collect_readiness_calls_snapshot_loader_once(monkeypatch, tmp_path):
    sentinel_connection = object()
    sentinel_snapshot = _snapshot_fixture()
    calls = []

    def fake_load(connection):
        calls.append(connection)
        return sentinel_snapshot

    monkeypatch.setattr(
        "app.services.longitudinal_readiness.load_database_snapshot", fake_load
    )
    report = collect_longitudinal_readiness(
        sentinel_connection,
        model_dir=tmp_path,
        code_heads={"0010"},
        generated_at="2026-08-25T00:00:00Z",
    )
    assert calls == [sentinel_connection]
    assert report.schema_version == "longitudinal_readiness.v1"
