from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.report_document import InputAudit

AuditPhase = Literal[
    "queued",
    "model_loading",
    "prediction",
    "standard_evidence",
    "rendering",
    "persistence",
    "terminal",
    "unknown",
]


class GenerationAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal[
        "phase_entered",
        "input_prepared",
        "invocation_started",
        "task_finished",
        "evidence_resolved",
        "terminal",
    ]
    phase: AuditPhase
    task: str | None = Field(
        default=None, max_length=160, pattern=r"^[a-zA-Z0-9_.:-]+$"
    )
    input_audit: InputAudit | None = None
    reason_code: str | None = Field(
        default=None, max_length=120, pattern=r"^[a-z0-9_]+$"
    )
    result_state: Literal["available", "unavailable", "unconfirmed"] | None = None

    @model_validator(mode="after")
    def matching_task(self):
        if self.input_audit is not None and self.input_audit.task != self.task:
            raise ValueError("audit_task_mismatch")
        return self


class GenerationAuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["generation_audit.v1"] = "generation_audit.v1"
    last_execution_phase: AuditPhase | None
    failure_phase: AuditPhase | None
    error_code: str | None
    event_count: int = Field(ge=0, le=256)
    events: list[GenerationAuditEvent] = Field(max_length=256)
    note: str = "仅展示已确认记录；缺少结束事件不代表模型未调用。"
