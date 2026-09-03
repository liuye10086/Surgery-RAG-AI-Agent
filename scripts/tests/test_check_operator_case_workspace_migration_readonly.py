"""Tests for the read-only operator case workspace migration checker."""

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "check_operator_case_workspace_migration_readonly.py"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location("operator_workspace_checker", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, rows=None, scalar=None, first=None):
        self.rows = list(rows or [])
        self.scalar_value = scalar
        self.first_value = first

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.first_value

    def scalar_one_or_none(self):
        return self.scalar_value


class Connection:
    def __init__(
        self,
        *,
        table_exists=True,
        revision="0019",
        sex_rows=None,
        counts=None,
        sex_constraint=None,
        evidence_tables=None,
    ):
        self.table_exists = table_exists
        self.revision = revision
        self.sex_rows = list(sex_rows or [])
        self.counts = counts or {
            "operator_case_count": 0,
            "missing_age_count": 0,
            "missing_sex_count": 0,
            "missing_baseline_stage_count": 0,
            "zero_visit_case_count": 0,
        }
        self.sex_constraint = sex_constraint
        self.evidence_tables = evidence_tables or set()
        self.statements = []

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        if "SET TRANSACTION READ ONLY" in sql:
            return Result()
        if "to_regclass('public.operator_cases')" in sql:
            return Result(scalar="operator_cases" if self.table_exists else None)
        if "FROM alembic_version" in sql:
            return Result(scalar=self.revision)
        if "GROUP BY sex" in sql:
            return Result(rows=self.sex_rows)
        if "missing_age_count" in sql:
            return Result(rows=[self.counts])
        if "conname = 'ck_operator_cases_sex'" in sql:
            return Result(first=self.sex_constraint)
        if "relname = ANY" in sql:
            return Result(rows=[{"relname": name} for name in self.evidence_tables])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_empty_database_is_safe_to_initialize():
    checker = _load_checker()
    connection = Connection(table_exists=False, revision=None)

    report = checker.collect_checks(connection, {"0020"})

    assert report["status"] == "PASS"
    assert report["mode"] == "empty_initialize"
    assert report["operator_case_count"] == 0
    assert connection.statements[0] == "SET TRANSACTION READ ONLY"


def test_existing_incomplete_profiles_are_reported_without_guessing_values():
    checker = _load_checker()
    counts = {
        "operator_case_count": 12,
        "missing_age_count": 1,
        "missing_sex_count": 2,
        "missing_baseline_stage_count": 3,
        "zero_visit_case_count": 0,
    }
    connection = Connection(
        sex_rows=[
            {"sex": None, "count": 2},
            {"sex": "female", "count": 5},
            {"sex": "male", "count": 5},
        ],
        counts=counts,
    )

    report = checker.collect_checks(connection, {"0020"})

    assert report["status"] == "PASS"
    assert report["mode"] == "existing_validate"
    assert report["missing_age_count"] == 1
    assert report["missing_sex_count"] == 2
    assert report["missing_baseline_stage_count"] == 3
    assert "historical_incomplete_cases_require_manual_completion" in report["warnings"]


def test_illegal_sex_blocks_without_mutating_sql():
    checker = _load_checker()
    connection = Connection(
        sex_rows=[{"sex": "unknown", "count": 2}],
        counts={
            "operator_case_count": 2,
            "missing_age_count": 0,
            "missing_sex_count": 0,
            "missing_baseline_stage_count": 0,
            "zero_visit_case_count": 0,
        },
    )

    report = checker.collect_checks(connection, {"0020"})

    assert report["status"] == "FAIL"
    assert report["invalid_sex_counts"] == {"unknown": 2}
    statements = " ".join(connection.statements).upper()
    assert all(token not in statements for token in ("UPDATE ", "INSERT ", "DELETE ", "ALTER ", "TRUNCATE "))


def test_zero_visit_case_blocks_migration():
    checker = _load_checker()
    connection = Connection(
        counts={
            "operator_case_count": 1,
            "missing_age_count": 0,
            "missing_sex_count": 0,
            "missing_baseline_stage_count": 0,
            "zero_visit_case_count": 1,
        }
    )

    report = checker.collect_checks(connection, {"0020"})

    assert report["status"] == "FAIL"
    assert report["zero_visit_case_count"] == 1


def test_postflight_requires_validated_constraint_and_evidence_tables():
    checker = _load_checker()
    connection = Connection(
        revision="0020",
        counts={
            "operator_case_count": 1,
            "missing_age_count": 0,
            "missing_sex_count": 0,
            "missing_baseline_stage_count": 0,
            "zero_visit_case_count": 0,
        },
        sex_constraint={"convalidated": False},
        evidence_tables={"operator_case_change_logs"},
    )

    report = checker.collect_checks(connection, {"0020"})

    assert report["mode"] == "postflight"
    assert report["status"] == "FAIL"
    assert report["constraint_validated"] is False
    assert report["idempotency_table_present"] is False


def test_unexpected_database_revision_is_blocked():
    checker = _load_checker()

    report = checker.collect_checks(Connection(revision="0017"), {"0020"})

    assert report["status"] == "BLOCKED"
    assert report["revision_compatible"] is False
