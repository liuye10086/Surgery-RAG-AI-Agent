from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
JobPhase = Literal[
    "queued",
    "model_loading",
    "prediction",
    "standard_evidence",
    "rendering",
    "persistence",
    "terminal",
]


class GenerationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    batch_id: UUID | None
    status: JobStatus
    report_status: Literal["generating", "completed", "failed", "cancelled"]
    phase: JobPhase
    revision: int = Field(ge=1)
    updated_at: datetime
    error_code: str | None = None
    message: str
    cancel_requested: bool = False
    legacy: bool = False
    failure_phase: str | None = None

    @model_validator(mode="after")
    def valid_identity(self):
        if self.batch_id is None and (
            not self.legacy or self.status in ("queued", "running")
        ):
            raise ValueError("generation_batch_required")
        if self.report_status != (
            "generating" if self.status in ("queued", "running") else self.status
        ):
            raise ValueError("generation_status_mismatch")
        return self


class JobAccepted(BaseModel):
    report_id: int
    batch_id: UUID
    status: JobStatus
    status_url: str
    events_url: str


class JobClaim(BaseModel):
    report_id: int
    batch_id: UUID
    lease_token: UUID
    lease_owner: str
    run_deadline: datetime
