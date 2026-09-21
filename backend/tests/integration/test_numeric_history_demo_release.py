"""Opt-in integration coverage for the isolated phase-five demo database.

This module never creates, migrates, truncates, or falls back to another
database. It runs only when TEST_DATABASE_URL explicitly names the frozen
loopback database prepared by the operator.
"""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from scripts.numeric_history_demo_release import (
    inspect_demo_database,
    seed_demo_database,
)
from scripts.run_numeric_history_acceptance import inspect_source, validate_database_url
from scripts.run_numeric_history_demo_release import wait_for_inflight


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "outputs/synthetic-prediction-cases/2026-09-15-switch-v2"


def _isolated_url() -> str | None:
    try:
        return validate_database_url()
    except ValueError:
        return None


DATABASE_URL = _isolated_url()
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="exact isolated TEST_DATABASE_URL is not configured",
)


def _engine():
    return create_engine(DATABASE_URL)


def test_actual_database_identity_migration_and_empty_business_tables():
    """The operator's pre-condition: run this module against a prepared empty database.

    Other integration modules commit their own rows, so this pre-condition only
    holds for a standalone run of this module — which is the documented command.
    """
    engine = _engine()
    try:
        with engine.connect() as connection:
            result = inspect_demo_database(connection)
        assert result == {
            "database": "surgery_rag_phase4_test",
            "alembic_version": "0031",
            "counts": {"users": 0, "operator_cases": 0, "ai_reports": 0},
        }
    finally:
        engine.dispose()


def _business_counts(connection):
    return {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("users", "operator_cases", "ai_reports")
    }


def test_seed_is_visible_together_then_fully_rolled_back():
    engine = _engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            before = _business_counts(connection)
            _clean_demo_tables(connection)
            seeded = seed_demo_database(connection, SOURCE, {"source": inspect_source(SOURCE)})
            assert _business_counts(connection) == {
                "users": 3,
                "operator_cases": len(seeded["case_ids"]),
                "ai_reports": 0,
            }
            transaction.rollback()
        with engine.connect() as connection:
            # The rollback restores whatever the database held before the seed.
            assert _business_counts(connection) == before
            assert connection.execute(
                text("SELECT current_database()")
            ).scalar_one() == "surgery_rag_phase4_test"
    finally:
        engine.dispose()


def test_seed_failure_rolls_back_users_diseases_and_cases(monkeypatch):
    from scripts import numeric_history_demo_release as release

    engine = _engine()
    try:
        with engine.connect() as connection:
            before = _business_counts(connection)
            original_diseases = connection.execute(
                text("SELECT code, operator_enabled FROM diseases ORDER BY code")
            ).all()
        monkeypatch.setattr(
            release,
            "seed_prediction_cases",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
        )
        with pytest.raises(RuntimeError, match="^injected$"):
            with engine.begin() as connection:
                seed_demo_database(connection, SOURCE, {"source": inspect_source(SOURCE)})
        with engine.connect() as connection:
            assert _business_counts(connection) == before
            assert connection.execute(
                text("SELECT code, operator_enabled FROM diseases ORDER BY code")
            ).all() == original_diseases
    finally:
        engine.dispose()


def test_empty_database_has_no_inflight_report_or_pdf_work():
    engine = _engine()
    owned = type(
        "AliveWorkers",
        (),
        {"assert_alive": lambda self, *names: None},
    )()
    try:
        result = wait_for_inflight(
            engine,
            owned,
            timeout_seconds=0,
            poll_seconds=0,
        )
        assert result == {
            "settled": True,
            "report_jobs": 0,
            "pdf_attempts": 0,
            "polls": 1,
        }
    finally:
        engine.dispose()


DEMO_TABLES = (
    "report_pdf_deliveries",
    "report_pdf_attempts",
    "report_pdf_archives",
    "report_file_cleanup_tasks",
    "report_deletion_tombstones",
    "report_generation_audit_events",
    "report_generation_jobs",
    "operator_idempotency_keys",
    "operator_case_change_logs",
    "ai_reports",
    "operator_case_visits",
    "operator_cases",
    "users",
)


def _clean_demo_tables(connection):
    """Reach the prepared empty state inside the caller's own transaction.

    TRUNCATE is transactional in PostgreSQL, so a case that starts from the
    empty demo state does not depend on which module ran before it.
    """
    connection.execute(
        text("TRUNCATE " + ", ".join(DEMO_TABLES) + " RESTART IDENTITY CASCADE")
    )


def _seed(connection):
    return seed_demo_database(connection, SOURCE, {"source": inspect_source(SOURCE)})


def _phase(connection, report_id, seq, phase, seconds, batch):
    connection.execute(
        text(
            "INSERT INTO report_generation_audit_events (report_id,event_seq,"
            "generation_batch_id,event_kind,phase,task,payload,payload_bytes,created_at) "
            "VALUES (:report_id,:seq,:batch,'phase_entered',:phase,NULL,"
            "jsonb_build_object('kind','phase_entered','phase',:phase),64,"
            "clock_timestamp() + make_interval(secs => :seconds))"
        ),
        {
            "report_id": report_id,
            "seq": seq,
            "batch": batch,
            "phase": phase,
            "seconds": seconds,
        },
    )


def _invocation(connection, report_id, seq, kind, seconds, batch):
    connection.execute(
        text(
            "INSERT INTO report_generation_audit_events (report_id,event_seq,"
            "generation_batch_id,event_kind,phase,task,payload,payload_bytes,created_at) "
            "VALUES (:report_id,:seq,:batch,:kind,'standard_evidence','report_narrative',"
            "jsonb_build_object('kind',:kind,'phase','standard_evidence'),64,"
            "clock_timestamp() + make_interval(secs => :seconds))"
        ),
        {
            "report_id": report_id,
            "seq": seq,
            "batch": batch,
            "kind": kind,
            "seconds": seconds,
        },
    )


def _published_report(connection, user_id, case_id, *, digest_ok=True):
    """Insert one completed report whose saved digests can be re-derived."""
    from scripts import numeric_history_demo_release as release
    from app.services.report_integrity import compute_input_snapshot_sha256

    from scripts.numeric_history_demo_release import HISTORY_SHA

    snapshot = {"schema_version": "numeric_report_input.v1", "case_id": case_id}
    document = {"schema_version": "numeric_report_document.v3", "case_id": case_id}
    evidence = {"schema_version": "numeric_evidence_snapshot.v1", "items": []}
    batch = "8b0f4f6e-0000-4000-8000-000000000001"
    report_id = connection.execute(
        text(
            "INSERT INTO ai_reports (user_id,query,department_ids,sources,retrieval_meta,"
            "content,status,analysis_type,operator_case_id,input_snapshot,"
            "input_snapshot_sha256,evidence_snapshot,evidence_snapshot_sha256,"
            "report_document,report_document_sha256,generation_batch_id,"
            "generation_fingerprint_version,generation_fingerprint,evidence_status,"
            "standard_evidence_status,reference_case_status) VALUES "
            "(:user_id,'demo', '[]'::jsonb,'[]'::jsonb,'{}'::jsonb,'','completed',"
            "'numeric_prediction',:case_id,:snapshot,:snapshot_sha,:evidence,:evidence_sha,"
            ":document,:document_sha,:batch,'v6',:fingerprint,'complete',"
            "'not_requested','available') RETURNING id"
        ),
        {
            "user_id": user_id,
            "case_id": case_id,
            "snapshot": json.dumps(snapshot),
            "snapshot_sha": compute_input_snapshot_sha256(snapshot),
            "evidence": json.dumps(evidence),
            "evidence_sha": release._canonical_sha256(evidence),
            "document": json.dumps(document),
            "document_sha": release._canonical_sha256(
                document if digest_ok else {"tampered": True}
            ),
            "batch": batch,
            "fingerprint": "a" * 64,
        },
    ).scalar_one()
    context = {
        "schema_version": "numeric_generation_context.v3",
        "algorithm": {"bundle_sha256": HISTORY_SHA},
    }
    connection.execute(
        text(
            "INSERT INTO report_generation_jobs (report_id,user_id,source_case_id,"
            "generation_context,context_sha256,status,phase,queue_deadline,finished_at,"
            "last_execution_phase,failure_phase) VALUES (:report_id,:user_id,:case_id,"
            ":context,:context_sha,'completed','terminal',clock_timestamp(),"
            "clock_timestamp() + interval '60 seconds','persistence',NULL)"
        ),
        {
            "report_id": report_id,
            "user_id": user_id,
            "case_id": case_id,
            "context": json.dumps(context),
            "context_sha": release._canonical_sha256(context),
        },
    )
    _phase(connection, report_id, 1, "model_loading", 0, batch)
    _phase(connection, report_id, 2, "prediction", 10, batch)
    _invocation(connection, report_id, 3, "invocation_started", 20, batch)
    _invocation(connection, report_id, 4, "task_finished", 30, batch)
    return report_id


def _published_archive(connection, report_id, pdf_bytes, archive_root, renderer=None):
    """Write one published original the way the real flow orders its rows."""
    from scripts.numeric_history_demo_release import RENDERER_SHA

    renderer = renderer or RENDERER_SHA
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    key = f"reports/{report_id}/{uuid4()}/document.pdf"
    connection.execute(
        text(
            "INSERT INTO report_pdf_archives (report_id,state,source_sha256,"
            "source_integrity,renderer_sha256) VALUES (:report_id,'queued',:sha,"
            "'valid',:renderer)"
        ),
        {"report_id": report_id, "sha": sha, "renderer": renderer},
    )
    attempt_id = connection.execute(
        text(
            "INSERT INTO report_pdf_attempts (report_id,status,phase,object_key,"
            "source_sha256,renderer_sha256,queue_deadline,started_at,finished_at) "
            "VALUES (:report_id,'completed','terminal',:key,:sha,:renderer,"
            "clock_timestamp(),clock_timestamp(),clock_timestamp()) RETURNING id"
        ),
        {"report_id": report_id, "key": key, "sha": sha, "renderer": renderer},
    ).scalar_one()
    connection.execute(
        text(
            "UPDATE report_pdf_archives SET state='ready',current_attempt_id=:attempt,"
            "published_attempt_id=:attempt,pdf_sha256=:sha,size_bytes=:size,"
            "page_count=1,archived_at=clock_timestamp() WHERE report_id=:report_id"
        ),
        {
            "report_id": report_id,
            "attempt": attempt_id,
            "sha": sha,
            "size": len(pdf_bytes),
        },
    )
    target = Path(archive_root).joinpath(*key.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf_bytes)
    return target


def test_evaluation_of_an_untouched_seeded_scope_reports_zero_not_a_pass():
    from scripts.numeric_history_demo_release import collect_demo_facts, build_release_metrics

    engine = _engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _clean_demo_tables(connection)
            seeded = _seed(connection)
            metrics = build_release_metrics(
                collect_demo_facts(connection, ROOT / "absent-archive", seeded)
            )
            assert metrics.jobs.model_dump() == {
                "queued": 0, "running": 0, "completed": 0, "failed": 0,
                "cancelled": 0, "unsettled": 0, "phase_timeouts": 0,
                "phase_timeout_phases": [],
            }
            assert metrics.history.model_dump() == {
                "verified_reports": 0, "mismatches": 0}
            assert metrics.pdf.ready == 0 and metrics.pdf.bytes_verified == 0
            assert metrics.identity.source_matches is False
            assert metrics.identity.history_bundle_matches is False
            transaction.rollback()
    finally:
        engine.dispose()


def test_records_outside_the_seeded_scope_fail_the_evaluation_closed():
    from scripts.numeric_history_demo_release import collect_demo_facts

    engine = _engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _clean_demo_tables(connection)
            seeded = _seed(connection)
            connection.execute(
                text(
                    "INSERT INTO users (username,email,hashed_password,role) VALUES "
                    "('demo-outsider','demo-outsider@test.invalid','x','ai_operator')"
                )
            )
            facts = collect_demo_facts(connection, ROOT / "absent-archive", seeded)
            assert facts["external_records"] == 1
            transaction.rollback()
    finally:
        engine.dispose()


def test_saved_identities_are_reverified_from_the_stored_bytes():
    from scripts.numeric_history_demo_release import build_release_metrics, collect_demo_facts

    engine = _engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _clean_demo_tables(connection)
            seeded = _seed(connection)
            operator = seeded["user_ids"]["primary_operator"]
            case_id = seeded["case_ids"][0]
            _published_report(connection, operator, case_id)
            _published_report(connection, operator, seeded["case_ids"][1], digest_ok=False)
            facts = collect_demo_facts(connection, ROOT / "absent-archive", seeded)
            metrics = build_release_metrics(facts)
            assert metrics.jobs.completed == 2
            assert metrics.history.model_dump() == {
                "verified_reports": 1, "mismatches": 1}
            assert metrics.llm_audit.model_dump() == {
                "invocation_started": 2, "task_finished": 2,
                "closed_reports": 2, "unclosed_reports": 0,
            }
            assert metrics.timings.model_loading.samples == 2
            assert metrics.timings.model_loading.total_ms == 20000
            transaction.rollback()
    finally:
        engine.dispose()


def test_archive_originals_are_re_read_and_hashed_without_writing():
    from scripts.numeric_history_demo_release import build_release_metrics, collect_demo_facts

    import fitz

    engine = _engine()
    archive_root = ROOT / "outputs" / "numeric-demo-integration-archive"
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _clean_demo_tables(connection)
            seeded = _seed(connection)
            operator = seeded["user_ids"]["primary_operator"]
            report_id = _published_report(connection, operator, seeded["case_ids"][0])
            document = fitz.open()
            document.new_page()
            pdf_bytes = document.tobytes()
            document.close()
            target = _published_archive(connection, report_id, pdf_bytes, archive_root)
            facts = collect_demo_facts(connection, archive_root, seeded)
            metrics = build_release_metrics(facts)
            assert metrics.pdf.model_dump() == {
                "ready": 1, "failed": 0, "missing": 0, "corrupt": 0,
                "downloads": 0, "bytes_verified": 1, "sha_mismatches": 0,
            }
            target.write_bytes(pdf_bytes + b"tampered")
            metrics = build_release_metrics(
                collect_demo_facts(connection, archive_root, seeded)
            )
            assert metrics.pdf.bytes_verified == 0
            assert metrics.pdf.sha_mismatches == 1
            transaction.rollback()
    finally:
        engine.dispose()
        if archive_root.exists():
            import shutil

            shutil.rmtree(archive_root, ignore_errors=True)
