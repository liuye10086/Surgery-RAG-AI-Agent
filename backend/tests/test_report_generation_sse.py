import json
from app.schemas.report_generation import GenerationStatus
from app.api.operator_report_jobs import encode_state, JobRequest
import pytest
from pydantic import ValidationError


def test_state_event_has_durable_identity():
    state = GenerationStatus(
        report_id=7,
        batch_id="11111111-1111-4111-8111-111111111111",
        status="cancelled",
        report_status="cancelled",
        phase="terminal",
        revision=5,
        updated_at="2026-09-07T00:00:00Z",
        message="已取消",
    )
    event = encode_state(state)
    assert event.startswith(
        "id: 11111111-1111-4111-8111-111111111111:5\nevent: state\n"
    )
    assert json.loads(event.split("data: ")[1])["status"] == "cancelled"
    assert "completed" not in event


def test_job_request_rejects_new_options():
    with pytest.raises(ValidationError):
        JobRequest(model_options={"x": 1})
