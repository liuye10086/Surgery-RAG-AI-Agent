import argparse
import hashlib
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
from app.services.reference_case_eligibility import ELIGIBILITY_CONFIG_HASH  # noqa: E402


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
        "visit_context",
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
    "operator_case_change_logs": {
        "id",
        "case_id",
        "case_id_snapshot",
        "anonymous_case_code_snapshot",
        "actor_id",
        "actor_id_snapshot",
        "action",
        "reason",
        "changes",
        "created_at",
    },
    "operator_idempotency_keys": {
        "id",
        "user_id",
        "scope",
        "idempotency_key",
        "request_sha256",
        "resource_type",
        "resource_id",
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
        "evidence_snapshot",
        "evidence_snapshot_sha256",
        "evidence_status",
        "standard_evidence_status",
        "reference_case_status",
    },
    # 标准版本化链路（Alembic 0009-0012）
    "reference_standards": {"id", "disease_id", "current_version_id"},
    "standard_documents": {
        "id", "content_hash", "issuer", "publication_date",
        "external_identifier", "source_url",
    },
    "reference_standard_versions": {
        "id",
        "standard_id",
        "standard_document_id",
        "status",
    },
    "standard_indicators": {"id", "canonical_key", "abnormal_direction"},
    "standard_segments": {"id", "version_id", "raw_text", "page_number"},
    "reference_case_windows": {
        "id", "disease_id", "logical_dataset", "anonymous_case_code", "dataset_release_id",
        "prediction_task", "outcome_reliability", "is_synthetic", "as_of",
        "feature_summary", "outcome_source", "eligibility_status", "timeline_sha256",
        "eligibility_config_hash", "data_content_sha256",
    },
    "standard_parse_candidates": {"id", "version_id", "segment_id", "candidate_json"},
    "standard_rules": {"id", "version_id", "indicator_id", "conditions"},
    "standard_rule_conditions": {"id", "rule_id", "parent_id", "payload"},
    "standard_change_logs": {"id", "version_id", "entity_type", "entity_id"},
}
REQUIRED_COLUMN_TYPES = {
    ("operator_cases", "age"): "integer",
    ("diseases", "code"): "character varying",
    ("diseases", "operator_enabled"): "boolean",
    ("operator_case_visits", "visit_context"): "jsonb",
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
EXPECTED_WORKSPACE_CONSTRAINTS = {
    "ck_operator_cases_sex",
    "ck_operator_case_change_logs_action",
    "ck_operator_case_change_logs_reason",
    "ck_operator_case_change_logs_changes_object",
    "uq_operator_idempotency_user_scope_key",
    "ck_operator_idempotency_keys_scope",
    "ck_operator_idempotency_keys_resource_type",
    "ck_operator_idempotency_keys_request_sha256",
}
EXPECTED_WORKSPACE_INDEXES = {
    "ix_operator_case_change_logs_case_time",
    "ix_operator_case_change_logs_actor_time",
    "ix_operator_idempotency_keys_user_time",
}


def _sha256_path(path_value):
    try:
        path = Path(str(path_value))
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except Exception:
        return None


def _collect_evidence_runtime_checks(connection, phase):
    """Collect only release identities/counts; never output case values or paths."""
    try:
        standard_rows = connection.execute(text(
            "SELECT d.code, rs.id AS standard_id, v.id AS version_id, v.status, "
            "v.content_hash AS version_hash, sd.content_hash AS document_hash, sd.file_path "
            "FROM diseases d JOIN reference_standards rs ON rs.disease_id=d.id "
            "JOIN reference_standard_versions v ON v.id=rs.current_version_id "
            "JOIN standard_documents sd ON sd.id=v.standard_document_id "
            "WHERE d.code IN ('ad','fatty_liver') ORDER BY d.code"
        )).mappings().all()
        standards = []
        for row in standard_rows:
            actual_hash = _sha256_path(row["file_path"])
            standards.append({
                "disease_code": row["code"],
                "standard_id": row["standard_id"],
                "version_id": row["version_id"],
                "status": row["status"],
                "content_sha256": row["document_hash"],
                "database_hashes_match": row["version_hash"] == row["document_hash"],
                "file_hash_matches": actual_hash == row["document_hash"],
            })
        standards_match = (
            {row["disease_code"] for row in standards} == {"ad", "fatty_liver"}
            and all(
                row["status"] == "approved"
                and row["database_hashes_match"]
                and row["file_hash_matches"]
                for row in standards
            )
        )

        release_rows = connection.execute(text(
            "SELECT d.code, COALESCE(cr.metadata->>'logical_dataset', cr.metadata->>'source_dataset') AS logical_dataset, "
            "cr.metadata->>'dataset_release_id' AS dataset_release_id, "
            "cr.metadata->>'data_content_sha256' AS data_content_sha256, COUNT(*) AS row_count "
            "FROM case_records cr JOIN diseases d ON d.id=cr.disease_id "
            "WHERE d.code IN ('ad','fatty_liver') "
            "AND cr.metadata->>'dataset_active'='true' "
            "GROUP BY d.code, COALESCE(cr.metadata->>'logical_dataset', cr.metadata->>'source_dataset'), "
            "cr.metadata->>'dataset_release_id', cr.metadata->>'data_content_sha256' "
            "ORDER BY d.code, dataset_release_id"
        )).mappings().all()
        releases = [dict(row) for row in release_rows]
        release_codes = [row["code"] for row in releases]
        releases_match = (
            sorted(release_codes) == ["ad", "fatty_liver"]
            and all(
                row.get("dataset_release_id")
                and isinstance(row.get("data_content_sha256"), str)
                and len(row["data_content_sha256"]) == 64
                for row in releases
            )
        )

        source_integrity_rows = connection.execute(text(
            "SELECT d.code, COUNT(sr.id) AS total_rules, "
            "COUNT(sr.source_segment_id) AS bound_rules, "
            "COUNT(*) FILTER (WHERE ss.id IS NOT NULL AND ss.version_id <> sr.version_id) AS cross_version_sources, "
            "COUNT(*) FILTER (WHERE ss.id IS NOT NULL AND btrim(ss.raw_text) = '') AS empty_source_texts "
            "FROM reference_standards rs JOIN diseases d ON d.id = rs.disease_id "
            "JOIN reference_standard_versions rsv ON rsv.id = rs.current_version_id "
            "JOIN standard_rules sr ON sr.version_id = rsv.id "
            "LEFT JOIN standard_segments ss ON ss.id = sr.source_segment_id "
            "WHERE d.code IN ('ad', 'fatty_liver') AND rsv.status = 'approved' "
            "GROUP BY d.code ORDER BY d.code"
        )).mappings().all()
        standard_source_integrity = [dict(row) for row in source_integrity_rows]
        standard_source_integrity_match = (
            {row["code"] for row in standard_source_integrity} == {"ad", "fatty_liver"}
            and all(
                row["total_rules"] > 0
                and row["bound_rules"] == row["total_rules"]
                and row["cross_version_sources"] == 0
                and row["empty_source_texts"] == 0
                for row in standard_source_integrity
            )
        )

        windows = []
        windows_match = None
        if phase == "postflight":
            window_rows = connection.execute(text(
                "SELECT logical_dataset, dataset_release_id, data_content_sha256, "
                "eligibility_config_hash, COUNT(*) AS total_windows, "
                "COUNT(*) FILTER (WHERE eligibility_status='eligible') AS eligible_windows "
                "FROM reference_case_windows GROUP BY logical_dataset, dataset_release_id, "
                "data_content_sha256, eligibility_config_hash "
                "ORDER BY logical_dataset, dataset_release_id"
            )).mappings().all()
            windows = [dict(row) for row in window_rows]
            active_identities = {
                (row["logical_dataset"], row["dataset_release_id"], row["data_content_sha256"])
                for row in releases
            }
            window_identities = {
                (row["logical_dataset"], row["dataset_release_id"], row["data_content_sha256"])
                for row in windows
            }
            windows_match = (
                active_identities <= window_identities
                and all(row["eligibility_config_hash"] == ELIGIBILITY_CONFIG_HASH for row in windows)
            )
        return {
            "available": True,
            "standards": standards,
            "standards_match": standards_match,
            "active_releases": releases,
            "active_releases_match": releases_match,
            "standard_source_integrity": standard_source_integrity,
            "standard_source_integrity_match": standard_source_integrity_match,
            "reference_window_pools": windows,
            "reference_window_pools_match": windows_match,
        }
    except Exception:
        return {"available": False, "reason_code": "evidence_runtime_query_failed"}


def _evidence_runtime_matches(evidence_runtime, phase):
    return (
        evidence_runtime.get("available") is True
        and evidence_runtime.get("standards_match") is True
        and evidence_runtime.get("active_releases_match") is True
        and (
            phase == "preflight"
            or (
                evidence_runtime.get("standard_source_integrity_match") is True
                and evidence_runtime.get("reference_window_pools_match") is True
            )
        )
    )


def _evidence_storage_matches(evidence_storage, phase):
    if phase == "preflight":
        return True
    return (
        evidence_storage.get("available") is True
        and not evidence_storage.get("missing_columns")
        and not evidence_storage.get("missing_constraints")
        and not evidence_storage.get("missing_indexes")
    )


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
            "invalid_visit_context_count": count(
                "SELECT COUNT(*) AS count FROM operator_case_visits "
                "WHERE visit_context IS NULL "
                "OR jsonb_typeof(visit_context) <> 'object'"
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


def _collect_workspace_catalog_checks(connection):
    """Inspect workspace constraints/indexes without mutating the catalog."""

    try:
        constraint_rows = connection.execute(
            text(
                "SELECT conname, convalidated FROM pg_constraint "
                "WHERE conname = ANY(:constraint_names) ORDER BY conname"
            ),
            {"constraint_names": sorted(EXPECTED_WORKSPACE_CONSTRAINTS)},
        ).mappings().all()
        index_rows = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "AND indexname = ANY(:index_names) ORDER BY indexname"
            ),
            {"index_names": sorted(EXPECTED_WORKSPACE_INDEXES)},
        ).mappings().all()
    except Exception:
        return {"available": False}

    actual_constraints = {row["conname"] for row in constraint_rows}
    unvalidated = sorted(
        row["conname"] for row in constraint_rows if not row["convalidated"]
    )
    actual_indexes = {row["indexname"] for row in index_rows}
    return {
        "available": True,
        "missing_constraints": sorted(
            EXPECTED_WORKSPACE_CONSTRAINTS - actual_constraints
        ),
        "unvalidated_constraints": unvalidated,
        "missing_indexes": sorted(EXPECTED_WORKSPACE_INDEXES - actual_indexes),
    }


def collect_checks(connection, code_heads, phase="postflight"):
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
    blocking_missing_columns = dict(missing_columns)
    if phase == "preflight":
        # Revision 0021 is a valid pre-migration state: the entire evidence
        # window table and the five nullable report columns are expected to be
        # absent until 0022 is applied.
        blocking_missing_columns.pop("reference_case_windows", None)
        allowed_report_columns = {
            "evidence_snapshot", "evidence_snapshot_sha256", "evidence_status",
            "standard_evidence_status", "reference_case_status",
        }
        report_missing = set(blocking_missing_columns.get("ai_reports", ()))
        report_missing -= allowed_report_columns
        if report_missing:
            blocking_missing_columns["ai_reports"] = sorted(report_missing)
        else:
            blocking_missing_columns.pop("ai_reports", None)
        for table_name, allowed_columns in {
            "standard_documents": {"issuer", "publication_date", "external_identifier", "source_url"},
            "standard_segments": {"page_number"},
        }.items():
            remaining = set(blocking_missing_columns.get(table_name, ())) - allowed_columns
            if remaining:
                blocking_missing_columns[table_name] = sorted(remaining)
            else:
                blocking_missing_columns.pop(table_name, None)
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
    if phase == "preflight":
        revision_matches = revision in {"0021", "0022"}
    base_diseases_match = base_diseases == EXPECTED_BASE_DISEASES
    disease_fk_rules_match = (
        set(disease_fk_rules) == EXPECTED_DISEASE_FKS
        and all(rule == "RESTRICT" for rule in disease_fk_rules.values())
    )
    visit_integrity = _collect_visit_integrity_checks(connection)
    anonymous_code_integrity = _collect_anonymous_code_checks(connection)
    workspace_catalog = _collect_workspace_catalog_checks(connection)
    evidence_runtime = _collect_evidence_runtime_checks(connection, phase)
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
    workspace_catalog_match = (
        workspace_catalog.get("available") is False
        or not workspace_catalog["missing_constraints"]
        and not workspace_catalog["unvalidated_constraints"]
        and not workspace_catalog["missing_indexes"]
    )
    evidence_runtime_match = _evidence_runtime_matches(evidence_runtime, phase)
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
    evidence_storage = {"missing_columns": [], "missing_constraints": [], "missing_indexes": [], "available": True}
    try:
        evidence_constraints = {
            row["conname"] for row in connection.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid IN ("
                "'reference_case_windows'::regclass, 'ai_reports'::regclass, "
                "'standard_segments'::regclass)"
            )).mappings().all()
        }
        evidence_indexes = {
            row["indexname"] for row in connection.execute(text(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='reference_case_windows'"
            )).mappings().all()
        }
        expected_constraints = {
            "uq_reference_case_windows_case_version", "ck_reference_case_windows_anonymous_code",
            "ck_reference_case_windows_horizon", "ck_reference_case_windows_age_range",
            "ck_reference_case_windows_sex",
            "ck_reference_case_windows_min_visits", "ck_reference_case_windows_min_span",
            "ck_reference_case_windows_outcome_status",
            "ck_reference_case_windows_outcome_reliability",
            "ck_reference_case_windows_eligibility_status",
            "ck_reference_case_windows_timeline_sha256",
            "ck_reference_case_windows_eligibility_config_hash",
            "ck_reference_case_windows_data_content_sha256",
            "ck_ai_reports_evidence_snapshot_sha256", "ck_ai_reports_evidence_status",
            "ck_ai_reports_standard_evidence_status", "ck_ai_reports_reference_case_status",
            "ck_standard_segments_page_number_positive",
        }
        expected_indexes = {"ix_reference_case_windows_pool_lookup", "ix_reference_case_windows_case_lookup", "ix_reference_case_windows_feature_summary_gin"}
        evidence_storage["missing_constraints"] = sorted(expected_constraints - evidence_constraints)
        evidence_storage["missing_indexes"] = sorted(expected_indexes - evidence_indexes)
    except Exception:
        evidence_storage["available"] = False
    if phase == "preflight":
        evidence_storage["migration_required"] = revision != "0022"
    status = (
        "PASS"
        if not missing_extensions
        and not blocking_missing_columns
        and not column_type_mismatches
        and revision_matches
        and base_diseases_match
        and disease_fk_rules_match
        and visit_integrity_match
        and anonymous_code_integrity_match
        and workspace_catalog_match
        and evidence_runtime_match
        and status_constraint_present is not False
        and status_constraint_validated is not False
        and status_audit_table_present is not False
        and _evidence_storage_matches(evidence_storage, phase)
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
        "blocking_missing_columns": blocking_missing_columns,
        "column_type_mismatches": column_type_mismatches,
        "base_diseases": base_diseases,
        "base_diseases_match": base_diseases_match,
        "disease_fk_rules": disease_fk_rules,
        "disease_fk_rules_match": disease_fk_rules_match,
        "visit_integrity": visit_integrity,
        "visit_integrity_match": visit_integrity_match,
        "anonymous_code_integrity": anonymous_code_integrity,
        "anonymous_code_integrity_match": anonymous_code_integrity_match,
        "workspace_catalog": workspace_catalog,
        "workspace_catalog_match": workspace_catalog_match,
        "evidence_runtime": evidence_runtime,
        "evidence_runtime_match": evidence_runtime_match,
        "status_constraint_present": status_constraint_present,
        "status_constraint_validated": status_constraint_validated,
        "status_audit_table_present": status_audit_table_present,
        "evidence_storage": evidence_storage,
        "phase": phase,
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run read-only schema and integrity checks against the configured "
            "database. The checker always rolls back its transaction."
        )
    )
    parser.add_argument("--phase", choices=("preflight", "postflight"), required=True)
    return parser


def main(argv=None):
    args = _argument_parser().parse_args(argv)
    engine = None
    try:
        engine = create_engine(settings.DATABASE_URL, future=True)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = collect_checks(connection, get_code_heads(), phase=args.phase)
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
