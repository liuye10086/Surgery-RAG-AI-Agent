import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.report_job_repository import claim_next, update_phase, finish_job
from app.services.report_generation_audit import append_generation_audit
from app.schemas.report_generation_audit import GenerationAuditEvent


def test_audit_fenced_terminal_and_cascade(db, queued_report):
    claim = claim_next(db, "audit-worker")
    assert update_phase(db, claim, "prediction")
    event = GenerationAuditEvent(
        kind="input_prepared", phase="prediction", task="test_task"
    )
    assert append_generation_audit(db, claim, event)
    assert finish_job(db, claim, "failed", "prediction_failed")
    row = db.execute(
        text(
            "SELECT audit_event_count, failure_phase FROM report_generation_jobs WHERE report_id=:id"
        ),
        {"id": queued_report},
    ).one()
    assert row.failure_phase == "prediction"
    assert row.audit_event_count == 4
    assert not append_generation_audit(db, claim, event)
    with pytest.raises(DBAPIError, match="report_audit_immutable"):
        db.execute(
            text(
                "UPDATE report_generation_audit_events SET task='changed' WHERE report_id=:id"
            ),
            {"id": queued_report},
        )
    db.rollback()
    db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": queued_report})
    db.commit()
    assert (
        db.execute(
            text("SELECT count(*) FROM report_generation_audit_events")
        ).scalar_one()
        == 0
    )


def test_terminal_slot_survives_event_budget_exhaustion(db, queued_report):
    claim = claim_next(db, "audit-worker")
    event = GenerationAuditEvent(
        kind="input_prepared", phase="model_loading", task="test_task"
    )
    for _ in range(254):
        assert append_generation_audit(db, claim, event)
    with pytest.raises(ValueError, match="audit_limit_exceeded"):
        append_generation_audit(db, claim, event)
    assert finish_job(db, claim, "failed", "execution_protocol_invalid")
    assert (
        db.execute(
            text("SELECT count(*) FROM report_generation_audit_events")
        ).scalar_one()
        == 256
    )


def test_audit_failure_rolls_back_event_and_counters(db, queued_report, monkeypatch):
    claim = claim_next(db, "audit-worker")
    event = GenerationAuditEvent(
        kind="input_prepared", phase="model_loading", task="test_task"
    )
    original_commit = db.commit

    def fail():
        db.flush()
        raise RuntimeError("injected")

    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError, match="injected"):
        append_generation_audit(db, claim, event)
    monkeypatch.setattr(db, "commit", original_commit)
    assert (
        db.execute(
            text("SELECT count(*) FROM report_generation_audit_events")
        ).scalar_one()
        == 1
    )
    assert (
        db.execute(
            text("SELECT audit_event_count FROM report_generation_jobs")
        ).scalar_one()
        == 1
    )
