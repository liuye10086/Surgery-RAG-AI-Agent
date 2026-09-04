import importlib.util
import inspect
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from app.db.models import AIReport, StandardDocument, StandardSegment


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def _load_revision():
    path = BACKEND_ROOT / "alembic/versions/0022_operator_report_evidence.py"
    spec = importlib.util.spec_from_file_location("migration_0022_operator_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载迁移文件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evidence_revision_follows_0021():
    migration = _load_revision()
    assert migration.revision == "0022"
    assert migration.down_revision == "0021"


def test_reference_window_has_privacy_and_version_columns():
    from app.db.models import ReferenceCaseWindow

    columns = {column.name for column in ReferenceCaseWindow.__table__.columns}
    assert "patient_label" not in columns
    assert {
        "disease_id",
        "logical_dataset",
        "dataset_release_id",
        "prediction_task",
        "anonymous_case_code",
        "as_of",
        "horizon_days",
        "profile_schema_version",
        "outcome_value",
        "outcome_reliability",
        "is_synthetic",
        "source_trace",
        "feature_summary",
        "measurement_context_summary",
        "exclusion_reasons",
    }.issubset(columns)
    constraint_names = {constraint.name for constraint in ReferenceCaseWindow.__table__.constraints}
    assert "uq_reference_case_windows_case_version" in constraint_names
    assert "ck_reference_case_windows_anonymous_code" in constraint_names
    assert "ck_reference_case_windows_horizon" in constraint_names
    assert "ck_reference_case_windows_min_visits" in constraint_names
    assert "ck_reference_case_windows_min_span" in constraint_names

    index_names = {index.name for index in ReferenceCaseWindow.__table__.indexes}
    assert {
        "ix_reference_case_windows_pool_lookup",
        "ix_reference_case_windows_case_lookup",
        "ix_reference_case_windows_feature_summary_gin",
    }.issubset(index_names)


def test_report_evidence_columns_are_nullable_for_legacy():
    assert AIReport.__table__.columns["evidence_snapshot"].nullable is True
    assert AIReport.__table__.columns["evidence_snapshot_sha256"].nullable is True
    assert AIReport.__table__.columns["evidence_status"].nullable is True
    assert AIReport.__table__.columns["standard_evidence_status"].nullable is True
    assert AIReport.__table__.columns["reference_case_status"].nullable is True
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in AIReport.__table__.constraints
        if getattr(constraint, "name", None) and hasattr(constraint, "sqltext")
    }
    assert "available" in constraints["ck_ai_reports_standard_evidence_status"]
    assert "no_eligible_cases" in constraints["ck_ai_reports_reference_case_status"]


def test_standard_citation_columns_and_page_number_contract():
    assert {
        "issuer",
        "publication_date",
        "external_identifier",
        "source_url",
    }.issubset({column.name for column in StandardDocument.__table__.columns})
    assert "page_number" in StandardSegment.__table__.columns


def test_downgrade_refuses_nonempty_evidence_before_ddl():
    migration = _load_revision()
    bind = MagicMock()
    result = MagicMock()
    result.scalar_one.return_value = 1
    bind.execute.return_value = result
    migration_op = MagicMock()
    migration_op.get_bind.return_value = bind

    with patch.object(migration, "op", migration_op):
        with pytest.raises(RuntimeError, match="refusing_to_drop_nonempty_longitudinal_evidence"):
            migration.downgrade()

    assert not any(name.startswith("drop") for name, *_ in migration_op.method_calls)


def test_clean_schema_contains_evidence_contract():
    schema = (PROJECT_ROOT / "database/schema.sql").read_text(encoding="utf-8")
    for token in (
        "CREATE TABLE IF NOT EXISTS reference_case_windows",
        "evidence_snapshot_sha256",
        "standard_evidence_status",
        "reference_case_status",
        "publication_date",
        "external_identifier",
        "source_url",
        "page_number",
        "ck_reference_case_windows_anonymous_code",
    ):
        assert token in schema


def test_migration_uses_lock_and_guards_before_ddl():
    migration = _load_revision()
    source = inspect.getsource(migration.downgrade)
    assert "LOCK TABLE reference_case_windows, ai_reports, standard_documents, standard_segments IN SHARE MODE" in source
    assert "refusing_to_drop_nonempty_longitudinal_evidence" in source
    assert source.index("LOCK TABLE") < source.index("drop_table")
