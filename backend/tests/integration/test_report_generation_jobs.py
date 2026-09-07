from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.services.report_job_repository import (
    claim_next,
    heartbeat,
    finish_job,
    reap_expired,
)


def test_only_one_worker_claims_one_job(integration_engine, queued_report):
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    barrier = Barrier(2)

    def take(owner):
        with factory() as db:
            barrier.wait(timeout=5)
            return claim_next(db, owner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(take, ["worker-a", "worker-b"]))
    assert sum(v is not None for v in values) == 1


def test_expired_worker_cannot_renew_or_finish(db, queued_report):
    claim = claim_next(db, "worker-a")
    db.execute(
        text(
            "UPDATE report_generation_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE report_id=:id"
        ),
        {"id": queued_report},
    )
    db.commit()
    assert heartbeat(db, claim) is False
    assert finish_job(db, claim, "failed", "prediction_failed") is False
    assert reap_expired(db) == 1
    assert reap_expired(db) == 0
    assert (
        db.execute(
            text("SELECT status FROM ai_reports WHERE id=:id"), {"id": queued_report}
        ).scalar_one()
        == "failed"
    )


def test_wrong_token_cannot_finish(db, queued_report):
    claim = claim_next(db, "worker-a")
    assert (
        finish_job(
            db,
            claim.model_copy(update={"lease_token": uuid4()}),
            "failed",
            "prediction_failed",
        )
        is False
    )
    assert heartbeat(db, claim) is True


def ready_publication(db, report_id):
    from backend.tests.report_document_fixtures import demo_inputs
    from app.db.models import AIReport, ReportGenerationJob
    from app.services.report_document_builder import build_report_document
    from app.services.report_publication import build_publication
    from app.services.report_integrity import compute_input_snapshot_sha256
    from app.services.report_job_repository import context_hash

    snapshot, context, audited, evidence = demo_inputs()
    report = db.get(AIReport, report_id)
    job = db.get(ReportGenerationJob, report_id)
    report.input_snapshot = snapshot
    report.input_snapshot_sha256 = compute_input_snapshot_sha256(snapshot)
    report.generation_batch_id = snapshot["generation_batch_id"]
    job.generation_context = context.model_dump(mode="json")
    job.context_sha256 = context_hash(job.generation_context)
    db.commit()
    doc = build_report_document(
        report_id,
        report.created_at,
        snapshot,
        context,
        audited.prediction,
        audited.model_runs,
        evidence,
    )
    return build_publication(snapshot, audited.prediction, evidence, doc)


def test_fenced_publication_updates_job_and_report_atomically(db, queued_report):
    from app.services.report_job_repository import publish_completed

    pub = ready_publication(db, queued_report)
    claim = claim_next(db, "worker-a")
    assert (
        publish_completed(db, claim.model_copy(update={"lease_token": uuid4()}), pub)
        is False
    )
    assert publish_completed(db, claim, pub) is True
    assert publish_completed(db, claim, pub) is False
    row = db.execute(
        text(
            "SELECT r.status, j.status, r.report_document, r.generation_fingerprint_version FROM ai_reports r JOIN report_generation_jobs j ON j.report_id=r.id WHERE r.id=:id"
        ),
        {"id": queued_report},
    ).one()
    assert row[0:2] == ("completed", "completed")
    assert row[2]["identity"]["report_id"] == queued_report
    assert row[3] == "v2"


def test_cancellation_and_publication_have_one_terminal_winner(
    db, queued_report, integration_engine
):
    from app.services.report_job_repository import publish_completed
    from app.services.report_generation_service import cancel_report_job

    pub = ready_publication(db, queued_report)
    claim = claim_next(db, "worker-a")
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    barrier = Barrier(2)

    def complete():
        with factory() as session:
            barrier.wait(timeout=5)
            return publish_completed(session, claim, pub)

    def cancel():
        with factory() as session:
            barrier.wait(timeout=5)
            return cancel_report_job(session, 1, queued_report).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(complete)
        b = pool.submit(cancel)
        published = a.result()
        cancel_status = b.result()
    row = db.execute(
        text(
            "SELECT r.status,j.status FROM ai_reports r JOIN report_generation_jobs j ON j.report_id=r.id WHERE r.id=:id"
        ),
        {"id": queued_report},
    ).one()
    assert row[0] == row[1] == cancel_status
    assert row[0] == ("completed" if published else "cancelled")


def test_publication_flush_failure_keeps_both_rows_running(
    db, queued_report, monkeypatch
):
    import pytest
    from app.services.report_job_repository import publish_completed

    pub = ready_publication(db, queued_report)
    claim = claim_next(db, "worker-a")

    def fail():
        raise RuntimeError("test transaction failure")

    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        publish_completed(db, claim, pub)
    row = db.execute(
        text(
            "SELECT r.status,j.status,r.report_document FROM ai_reports r JOIN report_generation_jobs j ON j.report_id=r.id WHERE r.id=:id"
        ),
        {"id": queued_report},
    ).one()
    assert row == ("generating", "running", None)


def test_commit_response_failure_preserves_database_completion(
    db, queued_report, monkeypatch, integration_engine
):
    import pytest
    from app.services.report_job_repository import publish_completed

    pub = ready_publication(db, queued_report)
    claim = claim_next(db, "worker-a")
    original = db.commit

    def committed_then_disconnected():
        original()
        raise OSError("simulated lost commit response")

    monkeypatch.setattr(db, "commit", committed_then_disconnected)
    with pytest.raises(OSError):
        publish_completed(db, claim, pub)
    with integration_engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT r.status,j.status FROM ai_reports r JOIN report_generation_jobs j ON j.report_id=r.id WHERE r.id=:id"
            ),
            {"id": queued_report},
        ).one() == ("completed", "completed")


def test_finish_rechecks_lease_after_waiting_for_report_lock(
    db, queued_report, integration_engine
):
    import time

    claim = claim_next(db, "worker-a")
    db.execute(
        text(
            "UPDATE report_generation_jobs SET lease_expires_at=clock_timestamp()+interval '1 second' WHERE report_id=:id"
        ),
        {"id": queued_report},
    )
    db.commit()
    factory = sessionmaker(bind=integration_engine)
    with factory() as blocker:
        blocker.execute(
            text("SELECT id FROM ai_reports WHERE id=:id FOR UPDATE"),
            {"id": queued_report},
        )

        def finish():
            with factory() as session:
                return finish_job(session, claim, "failed", "prediction_failed")

        with ThreadPoolExecutor(1) as pool:
            result = pool.submit(finish)
            time.sleep(1.2)
            blocker.rollback()
            assert result.result(timeout=5) is False


def test_readonly_gate_cannot_mutate_and_detects_context_tamper(
    db, queued_report, integration_engine
):
    from scripts.check_operator_report_generation_readonly import collect_checks

    db.execute(
        text(
            "UPDATE report_generation_jobs SET context_sha256=repeat('0',64) WHERE report_id=:id"
        ),
        {"id": queued_report},
    )
    db.commit()
    with integration_engine.connect() as connection:
        checks = collect_checks(connection, "postflight")
        assert checks["context_invalid"] == 1
        assert (
            connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        )
    assert (
        db.execute(
            text("SELECT status FROM report_generation_jobs WHERE report_id=:id"),
            {"id": queued_report},
        ).scalar_one()
        == "queued"
    )


def test_heartbeat_has_bounded_database_lock_wait(
    db, queued_report, integration_engine
):
    import time
    import pytest
    from sqlalchemy.exc import DBAPIError
    from app.services.report_job_repository import heartbeat

    claim = claim_next(db, "worker-a")
    factory = sessionmaker(bind=integration_engine)
    with factory() as blocker:
        blocker.execute(
            text(
                "SELECT report_id FROM report_generation_jobs WHERE report_id=:id FOR UPDATE"
            ),
            {"id": queued_report},
        )
        started = time.monotonic()
        with factory() as session, pytest.raises(DBAPIError):
            heartbeat(session, claim)
        assert time.monotonic() - started < 8
