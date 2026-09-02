import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check_operator_case_status_migration_readonly.py"
spec = importlib.util.spec_from_file_location("status_checker", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class Result:
    def __init__(self, rows=None, first=None):
        self.rows = rows or []
        self.first_value = first
    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.first_value


class Connection:
    def __init__(self, rows): self.rows = rows; self.statements = []
    def execute(self, statement, params=None):
        sql = str(statement); self.statements.append(sql)
        if "SET TRANSACTION READ ONLY" in sql: return Result()
        if "GROUP BY status" in sql: return Result(self.rows)
        if "pg_constraint" in sql: return Result(first={"convalidated": True})
        if "pg_class" in sql: return Result(first=(1,))
        raise AssertionError(sql)


def test_empty_database_is_safe_to_initialize():
    report = checker.collect_checks(Connection([]))
    assert report["status"] == "PASS"
    assert report["mode"] == "empty_initialize"
    assert report["unknown_status_counts"] == {}


def test_unknown_status_blocks_migration_without_mutation():
    conn = Connection([{"status": "active", "count": 2}, {"status": "paused", "count": 1}])
    report = checker.collect_checks(conn)
    assert report["status"] == "FAIL"
    assert report["unknown_status_counts"] == {"paused": 1}
    assert all(token not in " ".join(conn.statements).upper() for token in ("UPDATE", "DELETE", "ALTER", "INSERT"))


def test_null_status_is_reported():
    report = checker.collect_checks(Connection([{"status": None, "count": 1}]))
    assert report["status"] == "FAIL"
    assert report["null_status_count"] == 1

