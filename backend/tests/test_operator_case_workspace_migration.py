"""Storage contracts for the operator case workspace migration."""

import importlib.util
import inspect
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def _load_revision():
    path = BACKEND_ROOT / "alembic/versions/0020_operator_case_workspace.py"
    spec = importlib.util.spec_from_file_location("migration_0020_workspace", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载迁移文件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint(table, name: str):
    return next(item for item in table.constraints if item.name == name)


def _foreign_key(model, column_name: str):
    return next(iter(model.__table__.columns[column_name].foreign_keys))


def test_workspace_models_define_audit_idempotency_and_sex_contracts():
    from app.db.models import (
        OperatorCase,
        OperatorCaseChangeLog,
        OperatorIdempotencyKey,
    )

    sex_constraint = _constraint(OperatorCase.__table__, "ck_operator_cases_sex")
    assert "sex IS NULL" in str(sex_constraint.sqltext)
    assert "'male'" in str(sex_constraint.sqltext)
    assert "'female'" in str(sex_constraint.sqltext)

    assert OperatorCaseChangeLog.__tablename__ == "operator_case_change_logs"
    assert {
        "case_id",
        "case_id_snapshot",
        "anonymous_case_code_snapshot",
        "actor_id",
        "actor_id_snapshot",
        "action",
        "reason",
        "changes",
        "created_at",
    } == {column.name for column in OperatorCaseChangeLog.__table__.columns} - {"id"}

    assert OperatorIdempotencyKey.__tablename__ == "operator_idempotency_keys"
    assert {
        "user_id",
        "scope",
        "idempotency_key",
        "request_sha256",
        "resource_type",
        "resource_id",
        "created_at",
    } == {column.name for column in OperatorIdempotencyKey.__table__.columns} - {"id"}
    assert not OperatorIdempotencyKey.__table__.columns["resource_id"].foreign_keys


def test_workspace_model_foreign_keys_and_indexes_are_loss_safe():
    from app.db.models import OperatorCaseChangeLog, OperatorIdempotencyKey

    assert _foreign_key(OperatorCaseChangeLog, "case_id").ondelete == "SET NULL"
    assert _foreign_key(OperatorCaseChangeLog, "actor_id").ondelete == "SET NULL"
    assert _foreign_key(OperatorIdempotencyKey, "user_id").ondelete == "CASCADE"

    unique = _constraint(
        OperatorIdempotencyKey.__table__,
        "uq_operator_idempotency_user_scope_key",
    )
    assert tuple(column.name for column in unique.columns) == (
        "user_id",
        "scope",
        "idempotency_key",
    )
    assert {
        "ix_operator_case_change_logs_case_time",
        "ix_operator_case_change_logs_actor_time",
        "ix_operator_idempotency_keys_user_time",
    }.issubset(
        {
            index.name
            for table in (
                OperatorCaseChangeLog.__table__,
                OperatorIdempotencyKey.__table__,
            )
            for index in table.indexes
        }
    )


def test_disease_foreign_key_names_match_their_tables():
    from app.db.models import CaseRecord, OperatorCase

    assert _foreign_key(CaseRecord, "disease_id").name == "fk_case_records_disease"
    assert _foreign_key(OperatorCase, "disease_id").name == "fk_operator_cases_disease"


def test_workspace_migration_follows_0019_and_guards_evidence_on_downgrade():
    migration = _load_revision()

    assert migration.revision == "0020"
    assert migration.down_revision == "0019"
    module_source = inspect.getsource(migration)
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)
    assert "ck_operator_cases_sex" in upgrade_source
    assert "VALIDATE CONSTRAINT" in upgrade_source
    assert "operator_case_change_logs" in upgrade_source
    assert "operator_idempotency_keys" in upgrade_source
    assert "invalid_operator_case_sex" in module_source
    assert "refusing_to_drop_nonempty_operator_case_workspace_evidence" in downgrade_source


def test_clean_install_schema_matches_workspace_storage_contract():
    schema = (PROJECT_ROOT / "database/schema.sql").read_text(encoding="utf-8")

    for literal in (
        "CONSTRAINT ck_operator_cases_sex",
        "CREATE TABLE IF NOT EXISTS operator_case_change_logs",
        "CREATE TABLE IF NOT EXISTS operator_idempotency_keys",
        "CONSTRAINT uq_operator_idempotency_user_scope_key",
        "CONSTRAINT ck_operator_case_change_logs_action",
        "CONSTRAINT ck_operator_case_change_logs_changes_object",
        "ix_operator_case_change_logs_case_time",
        "ix_operator_case_change_logs_actor_time",
        "ix_operator_idempotency_keys_user_time",
    ):
        assert literal in schema


def test_readonly_baseline_requires_workspace_storage():
    path = PROJECT_ROOT / "scripts/check_database_readonly.py"
    spec = importlib.util.spec_from_file_location("workspace_readonly_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert {
        "operator_case_change_logs",
        "operator_idempotency_keys",
    }.issubset(module.REQUIRED_COLUMNS)
    assert {
        "ck_operator_cases_sex",
        "ck_operator_case_change_logs_action",
        "ck_operator_case_change_logs_reason",
        "ck_operator_case_change_logs_changes_object",
        "uq_operator_idempotency_user_scope_key",
        "ck_operator_idempotency_keys_scope",
        "ck_operator_idempotency_keys_resource_type",
        "ck_operator_idempotency_keys_request_sha256",
    } == module.EXPECTED_WORKSPACE_CONSTRAINTS
    assert {
        "ix_operator_case_change_logs_case_time",
        "ix_operator_case_change_logs_actor_time",
        "ix_operator_idempotency_keys_user_time",
    } == module.EXPECTED_WORKSPACE_INDEXES
