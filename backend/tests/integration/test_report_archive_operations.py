import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text, event
from app.services.report_pdf_errors import PdfError
from scripts.backup_report_archive_inventory import build_inventory, replay_deletions
from scripts.check_operator_report_archives_readonly import collect_checks
from backend.tests.integration.test_report_pdf_delivery import (
    archived,
    completed_report,
)


def test_gate_verifies_files_without_mutation(db, integration_engine, archived):
    report_id, storage, candidate = archived
    statements = []

    def capture(conn, cursor, sql, params, context, many):
        statements.append(sql)

    event.listen(integration_engine, "before_cursor_execute", capture)
    try:
        with integration_engine.connect() as connection:
            result = collect_checks(connection, verify_files=True, root=storage.root)
        assert result["schema_ready"] and result["invalid_sources"] == 0
        assert result["missing_files"] == result["corrupt_files"] == 0
        storage.candidate_path(candidate.object_key).unlink()
        with integration_engine.connect() as connection:
            result = collect_checks(connection, verify_files=True, root=storage.root)
        assert result["missing_files"] == 1
    finally:
        event.remove(integration_engine, "before_cursor_execute", capture)
    assert not any(
        sql.lstrip()
        .upper()
        .startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "TRUNCATE"))
        for sql in statements
    )
    assert (
        db.execute(text("SELECT state FROM report_pdf_archives")).scalar_one()
        == "ready"
    )


def pg_tool(name):
    executable = shutil.which(name)
    if executable:
        return executable
    candidate = Path("C:/Program Files/PostgreSQL/18/bin") / (name + ".exe")
    if candidate.is_file():
        return str(candidate)
    pytest.fail("PostgreSQL backup tools are required for restore acceptance")


def test_old_backup_restoration_replays_newer_deletions(
    db, integration_engine, archived, tmp_path
):
    from sqlalchemy.engine import make_url
    from scripts.seed_operator_report_e2e import require_test_database

    report_id, storage, candidate = archived
    source_url = make_url(os.environ["TEST_DATABASE_URL"])
    require_test_database(str(source_url))
    name = "archive_restore_" + uuid4().hex + "_test"
    target_url = source_url.set(database=name)
    admin = create_engine(
        source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    target = None
    env = {
        **os.environ,
        "PGHOST": source_url.host,
        "PGPORT": str(source_url.port or 5432),
        "PGUSER": source_url.username,
    }
    if source_url.password:
        env["PGPASSWORD"] = source_url.password
    backup = tmp_path / "isolated.dump"
    try:
        inventory = build_inventory(
            integration_engine, storage.root, "test-before-delete"
        )
        subprocess.run(
            [
                pg_tool("pg_dump"),
                "-Fc",
                "--no-owner",
                "-d",
                source_url.database,
                "-f",
                str(backup),
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        original = storage.candidate_path(candidate.object_key).read_bytes()
        from app.services.report_archive_storage import ArchiveStorage

        restored_storage = ArchiveStorage(tmp_path / "restored-files")
        restored_storage.write_candidate(candidate.object_key, original)
        db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": report_id})
        db.commit()
        newer = build_inventory(integration_engine, storage.root, "test-after-delete")
        with admin.connect() as conn:
            conn.execute(text('CREATE DATABASE "' + name + '"'))
        subprocess.run(
            [pg_tool("pg_restore"), "--no-owner", "-d", name, str(backup)],
            env=env,
            check=True,
            capture_output=True,
        )
        target = create_engine(target_url)
        with target.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM ai_reports WHERE id=:id"),
                    {"id": report_id},
                ).scalar_one()
                == 1
            )
        assert replay_deletions(target, newer)["matched_reports"] == 1
        result = replay_deletions(target, newer, apply=True)
        assert result["matched_reports"] == 1
        with target.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM ai_reports WHERE id=:id"),
                    {"id": report_id},
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM report_file_cleanup_tasks WHERE report_id_snapshot=:id"
                    ),
                    {"id": report_id},
                ).scalar_one()
                == 1
            )
        assert inventory["originals"][0]["pdf_sha256"] == candidate.pdf_sha256
        assert original.startswith(b"%PDF")
        from sqlalchemy.orm import Session
        from app.services.report_archive_cleanup import run_cleanup_once

        with Session(target) as restored_db:
            restored_db.execute(
                text(
                    "UPDATE report_file_cleanup_tasks SET next_attempt_at=clock_timestamp(),not_before_final_check=clock_timestamp()-interval '1 second'"
                )
            )
            restored_db.commit()
            assert (
                run_cleanup_once(
                    restored_db,
                    restored_storage.root,
                    delete_io=lambda root, key: ArchiveStorage(root).delete_attempt(
                        key
                    ),
                )
                is True
            )
        assert not restored_storage.candidate_path(candidate.object_key).exists()
    finally:
        if target:
            target.dispose()
        # Generated and validated local _test target; never remove source DB.
        assert (
            name.startswith("archive_restore_")
            and name.endswith("_test")
            and name != source_url.database
        )
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE IF EXISTS "' + name + '" WITH (FORCE)'))
        admin.dispose()
