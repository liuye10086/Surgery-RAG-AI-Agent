import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/check_database_readonly.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("database_baseline_checker", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载数据库基线脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        sql = str(statement)
        self.statements.append(sql)
        if "SET TRANSACTION READ ONLY" in sql:
            return _FakeResult([])
        if "server_version" in sql:
            return _FakeResult(["18.1"])
        if "pg_extension" in sql:
            return _FakeResult([
                {"extname": "pg_trgm", "extversion": "1.6"},
                {"extname": "uuid-ossp", "extversion": "1.1"},
                {"extname": "vector", "extversion": "0.8.3"},
            ])
        if "alembic_version" in sql:
            return _FakeResult(["test-head"])
        if "information_schema.columns" in sql:
            return _FakeResult([
                {"table_name": table_name, "column_name": column_name}
                for table_name, columns in _load_checker().REQUIRED_COLUMNS.items()
                for column_name in columns
            ])
        raise AssertionError(f"unexpected SQL: {sql}")


class DatabaseBaselineTests(unittest.TestCase):
    def test_checker_forces_read_only_transaction(self):
        checker = _load_checker()
        connection = _FakeConnection()
        report = checker.collect_checks(connection, {"test-head"})
        self.assertIn("SET TRANSACTION READ ONLY", connection.statements[0])
        self.assertEqual(report["status"], "PASS")

    def test_checker_requires_expected_extensions(self):
        checker = _load_checker()
        self.assertEqual(
            checker.REQUIRED_EXTENSIONS,
            {"vector", "uuid-ossp", "pg_trgm"},
        )

    def test_checker_fails_when_database_revision_is_not_a_code_head(self):
        checker = _load_checker()
        report = checker.collect_checks(_FakeConnection(), {"future-head"})
        self.assertFalse(report["revision_matches"])
        self.assertEqual(report["status"], "FAIL")

    def test_checker_source_contains_no_mutating_sql(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8").upper()
        for forbidden in ("DROP ", "TRUNCATE ", "INSERT ", "UPDATE ", "DELETE ", "ALTER "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
