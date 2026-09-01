"""Read-only preflight for Alembic revision 0014."""

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


EXPECTED_REVISION = "0013"
EXPECTED_DISEASES = {
    "脂肪肝": "fatty_liver",
    "阿尔茨海默病": "ad",
}
RELATED_TABLES = (
    "operator_cases",
    "case_records",
    "ai_reports",
    "reference_standards",
)


def _scalar(connection, sql: str) -> int:
    return int(connection.execute(text(sql)).scalar_one())


def collect_disease_migration_checks(connection) -> dict:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    revision = connection.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar_one_or_none()
    diseases = [
        dict(row)
        for row in connection.execute(
            text("SELECT id, name FROM diseases ORDER BY id")
        ).mappings().all()
    ]
    related_counts = {
        "operator_cases": _scalar(
            connection,
            "SELECT count(*) FROM operator_cases",
        ),
        "case_records": _scalar(
            connection,
            "SELECT count(*) FROM case_records",
        ),
        "ai_reports": _scalar(
            connection,
            "SELECT count(*) FROM ai_reports WHERE disease_id IS NOT NULL",
        ),
        "reference_standards": _scalar(
            connection,
            "SELECT count(*) FROM reference_standards",
        ),
    }
    orphan_counts = {
        table_name: _scalar(
            connection,
            f"SELECT count(*) FROM {table_name} item "
            "LEFT JOIN diseases d ON d.id = item.disease_id "
            "WHERE item.disease_id IS NOT NULL AND d.id IS NULL",
        )
        for table_name in RELATED_TABLES
    }

    expected_names = set(EXPECTED_DISEASES)
    actual_names = {row["name"] for row in diseases}
    missing_diseases = sorted(expected_names - actual_names)
    unexpected_diseases = [
        row for row in diseases if row["name"] not in expected_names
    ]
    revision_matches = revision == EXPECTED_REVISION
    has_orphans = any(orphan_counts.values())

    if not diseases:
        mode = "empty_initialize"
        catalog_matches = not any(related_counts.values())
    else:
        mode = "existing_backfill"
        catalog_matches = (
            len(diseases) == len(EXPECTED_DISEASES)
            and not missing_diseases
            and not unexpected_diseases
        )

    return {
        "status": (
            "PASS"
            if revision_matches and catalog_matches and not has_orphans
            else "FAIL"
        ),
        "mode": mode,
        "alembic_revision": revision,
        "expected_revision": EXPECTED_REVISION,
        "revision_matches": revision_matches,
        "diseases": diseases,
        "missing_diseases": missing_diseases,
        "unexpected_diseases": unexpected_diseases,
        "related_counts": related_counts,
        "orphan_counts": orphan_counts,
    }


def main() -> int:
    engine = None
    try:
        engine = create_engine(settings.DATABASE_URL, future=True)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = collect_disease_migration_checks(connection)
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
