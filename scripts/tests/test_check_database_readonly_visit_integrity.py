import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check_database_readonly.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("visit_integrity_checker", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, counts):
        self.counts = counts
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if "visit_index" in sql or "operator_case_visits" in sql:
            for key, value in self.counts.items():
                if key in sql:
                    return _Result([{"count": value}])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_checker_reports_visit_integrity_counts_and_keeps_queries_read_only():
    checker = _load_checker()
    connection = _Connection(
        {
            "visit_index IS NULL": 0,
            "HAVING COUNT(*) > 1": 0,
            "MIN(visit_index)": 0,
            "v.id IS NULL": 0,
            "c.id IS NULL": 0,
            "COUNT(*) > 10": 0,
        }
    )

    report = checker._collect_visit_integrity_checks(connection)

    assert report["available"] is True
    assert report["invalid_visit_index_count"] == 0
    assert report["duplicate_visit_index_case_count"] == 0
    assert report["visit_index_gap_case_count"] == 0
    assert report["zero_visit_case_count"] == 0
    assert report["over_limit_case_count"] == 0
    assert report["orphan_visit_count"] == 0
    assert all("UPDATE" not in sql.upper() and "DELETE" not in sql.upper() for sql in connection.statements)


def test_checker_marks_anomalies_as_failed_integrity():
    checker = _load_checker()
    connection = _Connection(
        {
            "visit_index IS NULL": 1,
            "HAVING COUNT(*) > 1": 1,
            "MIN(visit_index)": 1,
            "v.id IS NULL": 1,
            "c.id IS NULL": 1,
            "COUNT(*) > 10": 1,
        }
    )

    report = checker._collect_visit_integrity_checks(connection)

    assert report["available"] is True
    assert report["invalid_visit_index_count"] == 1
    assert report["duplicate_visit_index_case_count"] == 1
    assert report["visit_index_gap_case_count"] == 1
    assert report["zero_visit_case_count"] == 1
    assert report["over_limit_case_count"] == 1
    assert report["orphan_visit_count"] == 1
