"""Read-only deployment gate. Never prints connection strings or clinical JSON."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def evaluate_gate(checks, phase):
    if phase not in ("preflight", "postflight"):
        raise ValueError("invalid_phase")
    expected = {
        "context_invalid": 0,
        "terminal_mismatch": 0,
        "expired_jobs": 0,
        "legacy_generating": 0,
    }
    if phase == "postflight":
        expected.update(schema_ready=True, worker_ready=True)
    failed = [key for key, value in expected.items() if checks.get(key) != value]
    for key in ("input_invalid", "document_invalid", "evidence_ready", "accepting"):
        if key in checks:
            desired = (
                0
                if key.endswith("_invalid")
                else True
                if key == "evidence_ready"
                else False
            )
            if checks[key] != desired:
                failed.append(key)
    return {
        "status": "FAIL" if failed else "PASS",
        "phase": phase,
        "failed_checks": failed,
        "checks": checks,
    }


def collect_checks(connection, phase):
    from sqlalchemy import text, inspect
    from app.schemas.report_document import ReportGenerationContext
    from app.services.report_job_repository import context_hash
    from app.services.report_integrity import (
        compute_input_snapshot_sha256,
        verify_report_integrity,
    )

    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout='5000ms'"))
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    checks = dict(
        schema_ready=False,
        context_invalid=0,
        input_invalid=0,
        document_invalid=0,
        terminal_mismatch=0,
        expired_jobs=0,
        legacy_generating=0,
    )
    if "ai_reports" not in tables:
        return checks
    columns = {c["name"] for c in inspector.get_columns("ai_reports")}
    if "report_generation_jobs" not in tables:
        checks["legacy_generating"] = connection.execute(
            text("SELECT count(*) FROM ai_reports WHERE status='generating'")
        ).scalar_one()
        return checks
    indexes = {i["name"] for i in inspector.get_indexes("report_generation_jobs")}
    constraints = {
        c["name"] for c in inspector.get_check_constraints("report_generation_jobs")
    }
    head = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    checks["schema_ready"] = (
        head == "0024"
        and {
            "report_document",
            "report_document_sha256",
            "generation_fingerprint_version",
        }
        <= columns
        and {
            "uq_report_jobs_active_case",
            "ix_report_jobs_queued",
            "ix_report_jobs_running_lease",
        }
        <= indexes
        and {
            "ck_report_jobs_running",
            "ck_report_jobs_terminal",
            "ck_report_jobs_context_hash",
            "ck_report_jobs_queued",
        }
        <= constraints
    )
    checks["legacy_generating"] = connection.execute(
        text(
            "SELECT count(*) FROM ai_reports r LEFT JOIN report_generation_jobs j ON j.report_id=r.id WHERE r.status='generating' AND j.report_id IS NULL"
        )
    ).scalar_one()
    checks["terminal_mismatch"] = connection.execute(
        text(
            "SELECT count(*) FROM report_generation_jobs j JOIN ai_reports r ON r.id=j.report_id WHERE r.user_id<>j.user_id OR r.status<>CASE WHEN j.status IN ('queued','running') THEN 'generating' ELSE j.status END"
        )
    ).scalar_one()
    checks["expired_jobs"] = connection.execute(
        text(
            "SELECT count(*) FROM report_generation_jobs WHERE (status='queued' AND queue_deadline<=clock_timestamp()) OR (status='running' AND (lease_expires_at<=clock_timestamp() OR run_deadline<=clock_timestamp()))"
        )
    ).scalar_one()
    checks["queued"] = connection.execute(
        text("SELECT count(*) FROM report_generation_jobs WHERE status='queued'")
    ).scalar_one()
    checks["running"] = connection.execute(
        text("SELECT count(*) FROM report_generation_jobs WHERE status='running'")
    ).scalar_one()
    checks["oldest_queue_seconds"] = float(
        connection.execute(
            text(
                "SELECT coalesce(max(extract(epoch FROM clock_timestamp()-queued_at)),0) FROM report_generation_jobs WHERE status='queued'"
            )
        ).scalar_one()
    )
    for row in connection.execute(
        text("SELECT generation_context,context_sha256 FROM report_generation_jobs")
    ).mappings():
        try:
            ReportGenerationContext.model_validate(row["generation_context"])
            valid = context_hash(row["generation_context"]) == row["context_sha256"]
        except (ValueError, TypeError):
            valid = False
        checks["context_invalid"] += int(not valid)
    if checks["schema_ready"]:
        cursor = 0
        while True:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM ai_reports WHERE id>:cursor ORDER BY id LIMIT 100"
                    ),
                    {"cursor": cursor},
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            for row in rows:
                cursor = row["id"]
                if row["input_snapshot_sha256"]:
                    try:
                        valid = (
                            compute_input_snapshot_sha256(row["input_snapshot"])
                            == row["input_snapshot_sha256"]
                        )
                    except (ValueError, TypeError):
                        valid = False
                    checks["input_invalid"] += int(not valid)
                if (
                    row["report_document"] is not None
                    or row["generation_fingerprint_version"] == "v2"
                ):
                    result = verify_report_integrity(
                        row["input_snapshot"],
                        row["input_snapshot_sha256"],
                        row["generation_fingerprint"],
                        row["prediction_result"],
                        row["content"],
                        row["evidence_snapshot"],
                        row["evidence_snapshot_sha256"],
                        report_document=row["report_document"],
                        report_document_sha256=row["report_document_sha256"],
                        generation_fingerprint_version=row[
                            "generation_fingerprint_version"
                        ],
                    )
                    checks["document_invalid"] += int(result.status != "valid")
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preflight", "postflight"), required=True)
    parser.add_argument(
        "--worker-ready",
        action="store_true",
        help="Explicit local process-supervisor readiness assertion",
    )
    args = parser.parse_args()
    try:
        from app.core.config import settings
        from app.db.session import engine
        from sqlalchemy.orm import Session
        from sqlalchemy import text
        from app.db.models import Disease, ReferenceCaseWindow
        from app.services.evidence_bundle import preflight_evidence_versions

        with engine.connect() as connection:
            checks = collect_checks(connection, args.phase)
        checks.update(
            worker_ready=args.worker_ready, accepting=settings.REPORT_JOBS_ACCEPTING
        )
        if args.phase == "postflight":
            checks["evidence_ready"] = True
            for disease in ("fatty_liver", "ad"):
                with Session(
                    engine.execution_options(
                        isolation_level="REPEATABLE READ", postgresql_readonly=True
                    )
                ) as db:
                    db.execute(text("SET TRANSACTION READ ONLY"))
                    row = db.query(Disease).filter_by(code=disease).first()
                    if not row:
                        checks["evidence_ready"] = False
                        continue
                    token = preflight_evidence_versions(db, row.id, disease)
                    if token.reference_status:
                        checks["evidence_ready"] = False
                    elif (
                        db.query(ReferenceCaseWindow)
                        .filter_by(
                            disease_id=row.id,
                            dataset_release_id=token.dataset_release_id,
                            data_content_sha256=token.data_content_sha256,
                            eligibility_config_hash=token.eligibility_config_hash,
                        )
                        .count()
                        == 0
                    ):
                        checks["evidence_ready"] = False
        result = evaluate_gate(checks, args.phase)
    except Exception:
        result = {
            "status": "FAIL",
            "phase": args.phase,
            "failed_checks": ["gate_query_failed"],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
