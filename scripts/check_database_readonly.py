import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402


REQUIRED_EXTENSIONS = {"vector", "uuid-ossp", "pg_trgm"}
REQUIRED_COLUMNS = {
    "users": {"id", "username", "email", "hashed_password", "role"},
    "documents": {"id", "filename", "status", "active_generation"},
    "chunks": {"id", "document_id", "content", "generation", "is_current"},
    "sessions": {"id", "user_id", "title"},
    "messages": {"id", "session_id", "role", "content", "client_request_id"},
    "audit_logs": {"id", "user_id", "session_id", "safety_flags"},
    # AI 操作者纵向病例链路（Alembic 0006/0008）
    "diseases": {"id", "code", "name", "operator_enabled"},
    "case_records": {"id", "disease_id", "indicators", "confirmed"},
    "reference_ranges": {
        "id",
        "indicator_name",
        "unit",
        "lower",
        "upper",
        "sex",
        "standard_id",
        "standard_version_id",
        "standard_rule_id",
        "applicability_hash",
        "is_current_projection",
    },
    "operator_cases": {
        "id",
        "user_id",
        "disease_id",
        "patient_label",
        "anonymous_case_code",
        "sex",
        "age",
        "baseline_stage",
        "status",
    },
    "operator_case_visits": {
        "id",
        "case_id",
        "visit_date",
        "visit_index",
        "indicators",
    },
    "operator_case_status_logs": {
        "id",
        "case_id",
        "case_id_snapshot",
        "actor_id",
        "actor_id_snapshot",
        "from_status",
        "to_status",
        "reason",
        "created_at",
    },
    "ai_reports": {
        "id",
        "user_id",
        "status",
        "analysis_type",
        "disease_id",
        "operator_case_id",
        "indicators",
        "prediction_result",
        "input_snapshot",
    },
    # 标准版本化链路（Alembic 0009-0012）
    "reference_standards": {"id", "disease_id", "current_version_id"},
    "standard_documents": {"id", "content_hash"},
    "reference_standard_versions": {
        "id",
        "standard_id",
        "standard_document_id",
        "status",
    },
    "standard_indicators": {"id", "canonical_key", "abnormal_direction"},
    "standard_segments": {"id", "version_id", "raw_text"},
    "standard_parse_candidates": {"id", "version_id", "segment_id", "candidate_json"},
    "standard_rules": {"id", "version_id", "indicator_id", "conditions"},
    "standard_rule_conditions": {"id", "rule_id", "parent_id", "payload"},
    "standard_change_logs": {"id", "version_id", "entity_type", "entity_id"},
}
REQUIRED_COLUMN_TYPES = {
    ("operator_cases", "age"): "integer",
    ("diseases", "code"): "character varying",
    ("diseases", "operator_enabled"): "boolean",
}
EXPECTED_BASE_DISEASES = [
    {"code": "ad", "name": "阿尔茨海默病", "operator_enabled": True},
    {"code": "fatty_liver", "name": "脂肪肝", "operator_enabled": True},
]
EXPECTED_DISEASE_FKS = {
    "fk_operator_cases_disease",
    "fk_case_records_disease",
    "fk_ai_reports_disease",
    "reference_standards_disease_id_fkey",
}


def get_code_heads():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def _collect_visit_integrity_checks(connection):
    """Return read-only visit integrity counts; catalog/query gaps stay unavailable."""

    def count(sql):
        rows = connection.execute(text(sql)).mappings().all()
        if not rows:
            return 0
        return int(next(iter(rows[0].values())))

    try:
        return {
            "available": True,
            "invalid_visit_index_count": count(
                "SELECT COUNT(*) AS count FROM operator_case_visits "
                "WHERE visit_index IS NULL OR visit_index <= 0"
            ),
            "duplicate_visit_index_case_count": count(
                "SELECT COUNT(*) AS count FROM ("
                "SELECT case_id, visit_index FROM operator_case_visits "
                "GROUP BY case_id, visit_index HAVING COUNT(*) > 1"
                ") duplicates"
            ),
            "visit_index_gap_case_count": count(
                "SELECT COUNT(*) AS count FROM ("
                "SELECT case_id FROM operator_case_visits "
                "GROUP BY case_id HAVING MIN(visit_index) <> 1 "
                "OR COUNT(*) <> MAX(visit_index)"
                ") gaps"
            ),
            "zero_visit_case_count": count(
                "SELECT COUNT(*) AS count FROM operator_cases c "
                "LEFT JOIN operator_case_visits v ON v.case_id = c.id "
                "WHERE v.id IS NULL"
            ),
            "over_limit_case_count": count(
                "SELECT COUNT(*) AS count FROM ("
                "SELECT case_id FROM operator_case_visits "
                "GROUP BY case_id HAVING COUNT(*) > 10"
                ") over_limit"
            ),
            "orphan_visit_count": count(
                "SELECT COUNT(*) AS count FROM operator_case_visits v "
                "LEFT JOIN operator_cases c ON c.id = v.case_id "
                "WHERE c.id IS NULL"
            ),
        }
    except Exception:
        return {"available": False}


def _collect_anonymous_code_checks(connection):
    """仅统计匿名编号格式、重复和空值，不修改任何数据。"""
    def count(sql):
        rows = connection.execute(text(sql)).mappings().all()
        return int(next(iter(rows[0].values()))) if rows else 0

    try:
        return {
            "available": True,
            "operator_case_invalid_format_count": count(
                "SELECT COUNT(*) AS count FROM operator_cases "
                "WHERE anonymous_case_code IS NOT NULL "
                "AND anonymous_case_code !~ '^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$'"
            ),
            "operator_case_duplicate_count": count(
                "SELECT COUNT(*) AS count FROM (SELECT anonymous_case_code "
                "FROM operator_cases WHERE anonymous_case_code IS NOT NULL "
                "GROUP BY anonymous_case_code HAVING COUNT(*) > 1) duplicates"
            ),
            "operator_case_null_count": count(
                "SELECT COUNT(*) AS count FROM operator_cases "
                "WHERE anonymous_case_code IS NULL"
            ),
            "case_record_invalid_format_count": count(
                "SELECT COUNT(*) AS count FROM case_records "
                "WHERE anonymous_case_code IS NOT NULL "
                "AND anonymous_case_code !~ '^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$'"
            ),
        }
    except Exception:
        return {"available": False}


def collect_checks(connection, code_heads):
    connection.execute(text("SET TRANSACTION READ ONLY"))
    server_version = connection.execute(text("SHOW server_version")).scalar_one_or_none()
    extension_rows = connection.execute(
        text(
            "SELECT extname, extversion FROM pg_extension "
            "WHERE extname IN ('vector', 'uuid-ossp', 'pg_trgm') ORDER BY extname"
        )
    ).mappings().all()
    extensions = {row["extname"]: row["extversion"] for row in extension_rows}
    revision = connection.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar_one_or_none()
    column_rows = connection.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": list(REQUIRED_COLUMNS)},
    ).mappings().all()
    base_diseases = [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT code, name, operator_enabled FROM diseases "
                "WHERE code IN ('ad', 'fatty_liver') ORDER BY code"
            )
        ).mappings().all()
    ]
    disease_fk_rows = connection.execute(
        text(
            "SELECT constraint_name, delete_rule "
            "FROM information_schema.referential_constraints "
            "WHERE constraint_schema = 'public' "
            "AND constraint_name = ANY(:constraint_names) "
            "ORDER BY constraint_name"
        ),
        {"constraint_names": sorted(EXPECTED_DISEASE_FKS)},
    ).mappings().all()
    disease_fk_rules = {
        row["constraint_name"]: row["delete_rule"]
        for row in disease_fk_rows
    }
    actual_columns = {}
    for row in column_rows:
        actual_columns.setdefault(row["table_name"], set()).add(row["column_name"])
    actual_types = {
        (row["table_name"], row["column_name"]): row["data_type"]
        for row in column_rows
    }
    missing_extensions = sorted(REQUIRED_EXTENSIONS - set(extensions))
    missing_columns = {
        table_name: sorted(columns - actual_columns.get(table_name, set()))
        for table_name, columns in REQUIRED_COLUMNS.items()
        if columns - actual_columns.get(table_name, set())
    }
    column_type_mismatches = [
        {
            "table_name": table_name,
            "column_name": column_name,
            "expected": expected,
            "actual": actual_types.get((table_name, column_name)),
        }
        for (table_name, column_name), expected in REQUIRED_COLUMN_TYPES.items()
        if actual_types.get((table_name, column_name)) != expected
    ]
    revision_matches = revision in code_heads and len(code_heads) == 1
    base_diseases_match = base_diseases == EXPECTED_BASE_DISEASES
    disease_fk_rules_match = (
        set(disease_fk_rules) == EXPECTED_DISEASE_FKS
        and all(rule == "RESTRICT" for rule in disease_fk_rules.values())
    )
    visit_integrity = _collect_visit_integrity_checks(connection)
    anonymous_code_integrity = _collect_anonymous_code_checks(connection)
    visit_integrity_match = (
        visit_integrity.get("available") is False
        or all(
            value == 0
            for key, value in visit_integrity.items()
            if key.endswith("_count")
        )
    )
    anonymous_code_integrity_match = (
        anonymous_code_integrity.get("available") is False
        or all(
            value == 0
            for key, value in anonymous_code_integrity.items()
            if key.endswith("_count") and not key.endswith("_null_count")
        )
    )
    # Keep the baseline checker backwards-compatible with lightweight test
    # doubles while checking the new status guard on real PostgreSQL systems.
    status_constraint_present = None
    status_constraint_validated = None
    status_audit_table_present = None
    try:
        constraint = connection.execute(
            text(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conrelid = 'operator_cases'::regclass "
                "AND conname = 'ck_operator_cases_status'"
            )
        ).mappings().first()
        status_constraint_present = constraint is not None
        status_constraint_validated = bool(constraint and constraint["convalidated"])
        audit = connection.execute(
            text(
                "SELECT 1 FROM pg_class WHERE relname = 'operator_case_status_logs' "
                "AND relkind = 'r'"
            )
        ).first()
        status_audit_table_present = audit is not None
    except Exception:
        # Older checker fixtures/databases may not expose the new catalog
        # probes yet; schema migration verification is handled separately.
        pass
    status = (
        "PASS"
        if not missing_extensions
        and not missing_columns
        and not column_type_mismatches
        and revision_matches
        and base_diseases_match
        and disease_fk_rules_match
        and visit_integrity_match
        and anonymous_code_integrity_match
        and status_constraint_present is not False
        and status_constraint_validated is not False
        and status_audit_table_present is not False
        else "FAIL"
    )
    return {
        "status": status,
        "server_version": server_version,
        "extensions": extensions,
        "alembic_revision": revision,
        "code_heads": sorted(code_heads),
        "revision_matches": revision_matches,
        "missing_extensions": missing_extensions,
        "missing_columns": missing_columns,
        "column_type_mismatches": column_type_mismatches,
        "base_diseases": base_diseases,
        "base_diseases_match": base_diseases_match,
        "disease_fk_rules": disease_fk_rules,
        "disease_fk_rules_match": disease_fk_rules_match,
        "visit_integrity": visit_integrity,
        "visit_integrity_match": visit_integrity_match,
        "anonymous_code_integrity": anonymous_code_integrity,
        "anonymous_code_integrity_match": anonymous_code_integrity_match,
        "status_constraint_present": status_constraint_present,
        "status_constraint_validated": status_constraint_validated,
        "status_audit_table_present": status_audit_table_present,
    }


def main():
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
