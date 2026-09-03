"""Read-only preflight/postflight checks for operator case workspace revision 0020."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402


BASE_REVISION = "0019"
EVIDENCE_TABLES = {
    "operator_case_change_logs",
    "operator_idempotency_keys",
}
ALLOWED_SEXES = {"male", "female"}


def get_code_heads() -> set[str]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def _empty_report(revision: str | None, code_heads: set[str]) -> dict:
    revision_compatible = revision is None or revision == BASE_REVISION or revision in code_heads
    return {
        "status": "PASS" if revision_compatible else "BLOCKED",
        "mode": "empty_initialize",
        "alembic_revision": revision,
        "code_heads": sorted(code_heads),
        "revision_compatible": revision_compatible,
        "operator_case_count": 0,
        "invalid_sex_counts": {},
        "missing_age_count": 0,
        "missing_sex_count": 0,
        "missing_baseline_stage_count": 0,
        "zero_visit_case_count": 0,
        "constraint_present": False,
        "constraint_validated": False,
        "audit_table_present": False,
        "idempotency_table_present": False,
        "warnings": [],
    }


def collect_checks(connection, code_heads: set[str]) -> dict:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    table_exists = connection.execute(
        text("SELECT to_regclass('public.operator_cases')")
    ).scalar_one_or_none()
    revision = connection.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar_one_or_none()
    if table_exists is None:
        return _empty_report(revision, code_heads)

    sex_rows = connection.execute(
        text(
            "SELECT sex, count(*) AS count FROM operator_cases "
            "GROUP BY sex ORDER BY sex"
        )
    ).mappings().all()
    invalid_sex_counts = {
        str(row["sex"]): int(row["count"])
        for row in sex_rows
        if row["sex"] is not None and str(row["sex"]) not in ALLOWED_SEXES
    }
    count_rows = connection.execute(
        text(
            "SELECT "
            "count(*) AS operator_case_count, "
            "count(*) FILTER (WHERE c.age IS NULL) AS missing_age_count, "
            "count(*) FILTER (WHERE c.sex IS NULL) AS missing_sex_count, "
            "count(*) FILTER (WHERE c.baseline_stage IS NULL OR btrim(c.baseline_stage) = '') "
            "AS missing_baseline_stage_count, "
            "count(*) FILTER (WHERE NOT EXISTS ("
            "SELECT 1 FROM operator_case_visits v WHERE v.case_id = c.id"
            ")) AS zero_visit_case_count "
            "FROM operator_cases c"
        )
    ).mappings().all()
    counts = dict(count_rows[0]) if count_rows else {
        "operator_case_count": 0,
        "missing_age_count": 0,
        "missing_sex_count": 0,
        "missing_baseline_stage_count": 0,
        "zero_visit_case_count": 0,
    }
    counts = {key: int(value or 0) for key, value in counts.items()}

    constraint = connection.execute(
        text(
            "SELECT convalidated FROM pg_constraint "
            "WHERE conrelid = 'operator_cases'::regclass "
            "AND conname = 'ck_operator_cases_sex'"
        )
    ).mappings().first()
    evidence_rows = connection.execute(
        text(
            "SELECT relname FROM pg_class "
            "WHERE relkind = 'r' AND relname = ANY(:table_names)"
        ),
        {"table_names": sorted(EVIDENCE_TABLES)},
    ).mappings().all()
    present_tables = {row["relname"] for row in evidence_rows}

    revision_compatible = revision == BASE_REVISION or revision in code_heads
    postflight = revision in code_heads
    mode = (
        "postflight"
        if postflight
        else "empty_initialize"
        if counts["operator_case_count"] == 0
        else "existing_validate"
    )
    warnings = []
    if any(
        counts[key]
        for key in (
            "missing_age_count",
            "missing_sex_count",
            "missing_baseline_stage_count",
        )
    ):
        warnings.append("historical_incomplete_cases_require_manual_completion")

    constraint_present = constraint is not None
    constraint_validated = bool(constraint and constraint["convalidated"])
    audit_table_present = "operator_case_change_logs" in present_tables
    idempotency_table_present = "operator_idempotency_keys" in present_tables
    data_safe = not invalid_sex_counts and counts["zero_visit_case_count"] == 0
    structure_safe = (
        not postflight
        or constraint_present
        and constraint_validated
        and audit_table_present
        and idempotency_table_present
    )
    if not revision_compatible:
        status = "BLOCKED"
    elif data_safe and structure_safe:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "status": status,
        "mode": mode,
        "alembic_revision": revision,
        "code_heads": sorted(code_heads),
        "revision_compatible": revision_compatible,
        **counts,
        "invalid_sex_counts": invalid_sex_counts,
        "constraint_present": constraint_present,
        "constraint_validated": constraint_validated,
        "audit_table_present": audit_table_present,
        "idempotency_table_present": idempotency_table_present,
        "warnings": warnings,
    }


def main() -> int:
    engine = None
    try:
        engine = create_engine(settings.DATABASE_URL, future=True)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = collect_checks(connection, get_code_heads())
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
