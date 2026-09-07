from scripts.check_operator_report_archives_readonly import (
    evaluate_gate,
    collect_checks,
)
import pytest


def test_postflight_fails_closed_for_missing_schema_and_workers():
    result = evaluate_gate({}, "postflight")
    assert result["status"] == "FAIL"
    assert (
        "schema_ready" in result["failed_checks"]
        and "worker_ready" in result["failed_checks"]
    )


@pytest.mark.parametrize(
    "name",
    [
        "expired_attempts",
        "cleanup_overdue",
        "invalid_sources",
        "identity_errors",
        "counter_errors",
        "audit_errors",
        "referenced_cleanup",
        "missing_files",
        "corrupt_files",
        "orphan_files",
    ],
)
def test_each_integrity_failure_is_a_gate(name):
    checks = {
        key: 0
        for key in [
            "expired_attempts",
            "cleanup_overdue",
            "invalid_sources",
            "identity_errors",
            "counter_errors",
            "audit_errors",
            "referenced_cleanup",
            "missing_files",
            "corrupt_files",
            "orphan_files",
        ]
    }
    checks.update(
        schema_ready=True, worker_ready=True, renderer_ready=True, storage_ready=True
    )
    assert evaluate_gate(checks, "postflight")["status"] == "PASS"
    checks[name] = 1
    assert name in evaluate_gate(checks, "postflight")["failed_checks"]


def test_readonly_is_first_statement_before_metadata_inspection(monkeypatch):
    statements = []

    class Connection:
        def execute(self, sql):
            statements.append(str(sql))

    class Inspector:
        def get_table_names(self):
            assert statements[0] == "SET TRANSACTION READ ONLY"
            return []

    monkeypatch.setattr("sqlalchemy.inspect", lambda _: Inspector())
    assert not collect_checks(Connection())["schema_ready"]
    assert all(sql.startswith("SET ") for sql in statements)
