from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "check_operator_disease_migration_readonly.py"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "operator_disease_migration_checker",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载疾病迁移检查器：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class FakeConnection:
    def __init__(
        self,
        *,
        diseases,
        related_counts,
        orphan_counts=None,
        revision="0013",
    ):
        self.diseases = [dict(row) for row in diseases]
        self.related_counts = dict(related_counts)
        self.orphan_counts = {
            table: 0 for table in related_counts
        } | dict(orphan_counts or {})
        self.revision = revision
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            return _Result()
        if "FROM alembic_version" in sql:
            return _Result(scalar=self.revision)
        if sql == "SELECT id, name FROM diseases ORDER BY id":
            return _Result(rows=self.diseases)
        if sql.startswith("SELECT count(*) FROM") and "LEFT JOIN diseases" not in sql:
            table = sql.split()[3]
            return _Result(scalar=self.related_counts[table])
        if "LEFT JOIN diseases" in sql:
            table = sql.split("FROM ", 1)[1].split(" ", 1)[0]
            return _Result(scalar=self.orphan_counts[table])
        raise AssertionError(f"unexpected SQL: {sql}")


def _counts(**overrides):
    values = {
        "operator_cases": 0,
        "case_records": 0,
        "ai_reports": 0,
        "reference_standards": 0,
    }
    values.update(overrides)
    return values


def test_empty_database_is_safe_to_initialize():
    checker = _load_checker()
    connection = FakeConnection(diseases=[], related_counts=_counts())

    report = checker.collect_disease_migration_checks(connection)

    assert report["mode"] == "empty_initialize"
    assert report["status"] == "PASS"
    assert connection.statements[0] == "SET TRANSACTION READ ONLY"


def test_existing_two_disease_database_is_safe_to_backfill():
    checker = _load_checker()
    report = checker.collect_disease_migration_checks(
        FakeConnection(
            diseases=[
                {"id": 1, "name": "脂肪肝"},
                {"id": 2, "name": "阿尔茨海默病"},
            ],
            related_counts=_counts(
                operator_cases=3,
                case_records=8,
                ai_reports=2,
                reference_standards=2,
            ),
        )
    )

    assert report["mode"] == "existing_backfill"
    assert report["status"] == "PASS"
    assert report["missing_diseases"] == []
    assert report["unexpected_diseases"] == []


def test_third_disease_blocks_migration():
    checker = _load_checker()
    report = checker.collect_disease_migration_checks(
        FakeConnection(
            diseases=[
                {"id": 1, "name": "脂肪肝"},
                {"id": 2, "name": "阿尔茨海默病"},
                {"id": 3, "name": "胃癌"},
            ],
            related_counts=_counts(),
        )
    )

    assert report["status"] == "FAIL"
    assert report["unexpected_diseases"] == [{"id": 3, "name": "胃癌"}]


def test_empty_catalog_with_business_data_is_not_initializable():
    checker = _load_checker()
    report = checker.collect_disease_migration_checks(
        FakeConnection(
            diseases=[],
            related_counts=_counts(operator_cases=1),
        )
    )

    assert report["status"] == "FAIL"
    assert report["mode"] == "empty_initialize"


def test_orphan_reference_or_wrong_revision_blocks_migration():
    checker = _load_checker()
    report = checker.collect_disease_migration_checks(
        FakeConnection(
            diseases=[
                {"id": 1, "name": "脂肪肝"},
                {"id": 2, "name": "阿尔茨海默病"},
            ],
            related_counts=_counts(case_records=1),
            orphan_counts={"case_records": 1},
            revision="0012",
        )
    )

    assert report["status"] == "FAIL"
    assert report["revision_matches"] is False
    assert report["orphan_counts"]["case_records"] == 1


def test_checker_source_contains_no_mutating_sql():
    source = SCRIPT_PATH.read_text(encoding="utf-8").upper()
    for forbidden in ("DROP ", "TRUNCATE ", "INSERT ", "UPDATE ", "DELETE ", "ALTER "):
        assert forbidden not in source
