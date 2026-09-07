import pytest
from pydantic import ValidationError
from app.schemas.report_generation import GenerationStatus


def test_only_legacy_terminal_reports_may_have_no_batch():
    payload = dict(
        report_id=1,
        batch_id=None,
        status="completed",
        report_status="completed",
        phase="terminal",
        revision=1,
        updated_at="2026-09-07T00:00:00Z",
        message="已完成",
    )
    with pytest.raises(ValidationError):
        GenerationStatus(**payload)
    assert GenerationStatus(**payload, legacy=True).batch_id is None
    with pytest.raises(ValidationError):
        GenerationStatus(
            **{
                **payload,
                "status": "running",
                "report_status": "generating",
                "phase": "prediction",
            },
            legacy=True,
        )
