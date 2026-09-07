"""Read-only archive release gate. Prints aggregate facts and stable codes only."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def evaluate_gate(checks, phase):
    expected = {
        "expired_attempts": 0,
        "cleanup_overdue": 0,
        "invalid_sources": 0,
        "identity_errors": 0,
        "counter_errors": 0,
        "audit_errors": 0,
        "referenced_cleanup": 0,
    }
    if phase == "postflight":
        expected.update(
            schema_ready=True,
            worker_ready=True,
            renderer_ready=True,
            storage_ready=True,
        )
    for name in ("missing_files", "corrupt_files", "orphan_files"):
        if name in checks:
            expected[name] = 0
    failed = [name for name, value in expected.items() if checks.get(name) != value]
    return {
        "status": "FAIL" if failed else "PASS",
        "phase": phase,
        "failed_checks": failed,
        "checks": checks,
    }


def collect_checks(
    connection,
    *,
    phase="preflight",
    verify_files=False,
    root="",
    manifest="",
    worker_ready=False
):
    from sqlalchemy import text, inspect
    from sqlalchemy.orm import Session
    from app.services.report_read_service import (
        read_owned_report,
        build_pdf_source,
        source_digest,
    )
    from app.services.report_archive_storage import ArchiveStorage
    from app.services.report_pdf_renderer_manifest import load_renderer_manifest
    from app.services.report_pdf_errors import PdfError

    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout='5000ms'"))
    checks = dict(
        schema_ready=False,
        worker_ready=worker_ready,
        renderer_ready=False,
        storage_ready=False,
        expired_attempts=0,
        cleanup_overdue=0,
        invalid_sources=0,
        identity_errors=0,
        counter_errors=0,
        audit_errors=0,
        referenced_cleanup=0,
    )
    tables = set(inspect(connection).get_table_names())
    required = {
        "report_pdf_archives",
        "report_pdf_attempts",
        "report_pdf_deliveries",
        "report_file_cleanup_tasks",
        "report_deletion_tombstones",
        "report_generation_audit_events",
    }
    if not required <= tables:
        return checks
    checks["schema_ready"] = (
        connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        == "0026"
    )
    protected={'report_audit_immutable','pdf_original_immutable','pdf_delivery_immutable',
               'pdf_attempt_identity_immutable','report_pdf_attempt_cleanup','remember_report_deletion'}
    installed=set(connection.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgenabled='O'")).scalars())
    checks['schema_ready']=checks['schema_ready'] and protected<=installed
    queries = {
        "expired_attempts": "SELECT count(*) FROM report_pdf_attempts WHERE (status='queued' AND queue_deadline<=clock_timestamp()) OR (status='running' AND (lease_expires_at<=clock_timestamp() OR run_deadline<=clock_timestamp()))",
        "cleanup_overdue": "SELECT count(*) FROM report_file_cleanup_tasks WHERE state!='done' AND next_attempt_at<clock_timestamp()-interval '1 hour'",
        "identity_errors": "SELECT count(*) FROM report_pdf_archives a JOIN ai_reports r ON r.id=a.report_id LEFT JOIN report_pdf_attempts p ON p.id=a.published_attempt_id WHERE r.status!='completed' OR (a.published_attempt_id IS NOT NULL AND (p.status!='completed' OR a.pdf_sha256 IS NULL OR a.size_bytes IS NULL OR p.report_id!=a.report_id))",
        "counter_errors": "SELECT count(*) FROM report_pdf_archives a WHERE a.delivery_count!=(SELECT count(*) FROM report_pdf_deliveries d WHERE d.report_id=a.report_id)",
        "audit_errors": "SELECT count(*) FROM report_generation_jobs j WHERE j.audit_event_count!=(SELECT count(*) FROM report_generation_audit_events e WHERE e.report_id=j.report_id) OR j.audit_event_count>256 OR j.audit_bytes>8388608",
        "referenced_cleanup": "SELECT count(*) FROM report_file_cleanup_tasks c JOIN report_pdf_attempts p ON p.object_key=c.object_key JOIN report_pdf_archives a ON a.published_attempt_id=p.id",
    }
    for key, sql in queries.items():
        checks[key] = connection.execute(text(sql)).scalar_one()
    try:
        load_renderer_manifest(manifest)
        checks["renderer_ready"] = True
    except Exception:
        pass
    storage = None
    try:
        storage = ArchiveStorage(root, create=False)
        checks["storage_ready"] = True
    except Exception:
        pass
    rows = (
        connection.execute(
            text(
                "SELECT r.id,r.user_id,a.source_sha256,a.pdf_sha256,a.size_bytes,p.object_key FROM ai_reports r JOIN report_pdf_archives a ON a.report_id=r.id LEFT JOIN report_pdf_attempts p ON p.id=a.published_attempt_id"
            )
        )
        .mappings()
        .all()
    )
    with Session(bind=connection) as db:
        for row in rows:
            try:
                if (
                    source_digest(
                        build_pdf_source(
                            read_owned_report(db, row["user_id"], row["id"])
                        )
                    )
                    != row["source_sha256"]
                ):
                    raise ValueError()
            except Exception:
                checks["invalid_sources"] += 1
    if verify_files:
        checks.update(missing_files=0, corrupt_files=0, orphan_files=0)
        if storage is None:
            checks["missing_files"] = sum(bool(r["object_key"]) for r in rows)
        else:
            for row in rows:
                if not row["object_key"]:
                    continue
                try:
                    with storage.open_verified(
                        row["object_key"], row["pdf_sha256"], row["size_bytes"]
                    ):
                        pass
                except PdfError as error:
                    checks[
                        (
                            "missing_files"
                            if error.code == "pdf_original_missing"
                            else "corrupt_files"
                        )
                    ] += 1
            known = set(
                connection.execute(
                    text(
                        "SELECT object_key FROM report_pdf_attempts UNION SELECT object_key FROM report_file_cleanup_tasks"
                    )
                ).scalars()
            )
            # A read-only walk does not follow directory symlinks/reparse points.
            import os

            for folder, dirs, files in os.walk(storage.root, followlinks=False):
                dirs[:] = [
                    name
                    for name in dirs
                    if not (Path(folder) / name).is_symlink()
                    and not getattr(
                        (Path(folder) / name).lstat(), "st_file_attributes", 0
                    )
                    & 0x400
                ]
                for name in files:
                    relative = (
                        (Path(folder) / name).relative_to(storage.root).as_posix()
                    )
                    associated = str(Path(relative).parent / "document.pdf").replace(
                        "\\", "/"
                    )
                    if associated not in known:
                        checks["orphan_files"] += 1
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["preflight", "postflight"], required=True)
    parser.add_argument("--verify-files", action="store_true")
    parser.add_argument("--worker-ready", action="store_true")
    args = parser.parse_args(argv)
    from sqlalchemy import create_engine
    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            result = evaluate_gate(
                collect_checks(
                    connection,
                    phase=args.phase,
                    verify_files=args.verify_files,
                    root=settings.REPORT_ARCHIVE_ROOT,
                    manifest=settings.REPORT_PDF_RENDERER_MANIFEST,
                    worker_ready=args.worker_ready,
                ),
                args.phase,
            )
        print(json.dumps(result))
        return 0 if result["status"] == "PASS" else 1
    except Exception:
        print(json.dumps({"status": "FAIL", "code": "archive_readonly_check_failed"}))
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
