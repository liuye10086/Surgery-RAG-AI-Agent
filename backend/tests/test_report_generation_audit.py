from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services.report_job_repository import _terminal
from app.schemas.report_generation_audit import GenerationAuditEvent
from app.services.report_generation_audit import encode_audit_event


def test_failure_preserves_last_confirmed_phase():
    job = SimpleNamespace(
        phase="standard_evidence", revision=2, last_execution_phase="standard_evidence"
    )
    report = SimpleNamespace()
    _terminal(job, report, "failed", "worker_interrupted", datetime.now(timezone.utc))
    assert job.phase == "terminal"
    assert job.failure_phase == "standard_evidence"
    assert report.error_stage == "standard_evidence"


@pytest.mark.parametrize(
    "extra", [{"user_id": 1}, {"timestamp": "now"}, {"raw_value": 99}]
)
def test_event_rejects_untrusted_fields(extra):
    with pytest.raises(ValidationError):
        GenerationAuditEvent(kind="phase_entered", phase="prediction", **extra)


def test_event_has_finite_bounded_utf8_payload():
    event = GenerationAuditEvent(kind="phase_entered", phase="prediction")
    payload, size = encode_audit_event(event)
    assert payload["kind"] == "phase_entered"
    assert 0 < size <= 262144


def test_input_audit_field_budget():
    from app.schemas.report_document import InputAudit

    audit = InputAudit(
        task="task",
        fields=[{"name": f"field_{i}", "state": "present"} for i in range(1025)],
    )
    with pytest.raises(ValueError, match="audit_limit_exceeded"):
        encode_audit_event(
            GenerationAuditEvent(
                kind="input_prepared",
                phase="prediction",
                task="task",
                input_audit=audit,
            )
        )
