"""Read-only preflight/postflight checks for operator case status migration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from app.core.config import settings  # noqa: E402

ALLOWED_STATUSES = ("active", "archived")


def collect_checks(connection) -> dict:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    rows = [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT status, count(*) AS count "
                "FROM operator_cases GROUP BY status ORDER BY status"
            )
        ).mappings().all()
    ]
    operator_case_count = sum(int(row["count"]) for row in rows)
    status_counts = {
        str(row["status"]): int(row["count"])
        for row in rows
        if row["status"] is not None
    }
    null_status_count = sum(int(row["count"]) for row in rows if row["status"] is None)
    unknown_status_counts = {
        key: value for key, value in status_counts.items() if key not in ALLOWED_STATUSES
    }
    constraint = connection.execute(
        text(
            "SELECT conname, convalidated "
            "FROM pg_constraint "
            "WHERE conrelid = 'operator_cases'::regclass "
            "AND conname = 'ck_operator_cases_status'"
        )
    ).mappings().first()
    audit_table = connection.execute(
        text(
            "SELECT 1 FROM pg_class WHERE relname = 'operator_case_status_logs' "
            "AND relkind = 'r'"
        )
    ).first()
    constraint_present = constraint is not None
    constraint_validated = bool(constraint and constraint["convalidated"])
    audit_table_present = audit_table is not None
    mode = "empty_initialize" if operator_case_count == 0 else "existing_validate"
    safe = not null_status_count and not unknown_status_counts
    return {
        "status": "PASS" if safe else "FAIL",
        "mode": mode,
        "operator_case_count": operator_case_count,
        "status_counts": status_counts,
        "null_status_count": null_status_count,
        "unknown_status_counts": unknown_status_counts,
        "constraint_present": constraint_present,
        "constraint_validated": constraint_validated,
        "audit_table_present": audit_table_present,
    }


def main() -> int:
    engine = None
    try:
        engine = create_engine(settings.DATABASE_URL, future=True)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = collect_checks(connection)
            finally:
                transaction.rollback()
    except Exception as exc:
        report = {"status": "BLOCKED", "error_type": type(exc).__name__}
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

