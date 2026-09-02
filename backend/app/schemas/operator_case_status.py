"""Stable status contract for operator-owned longitudinal cases."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OperatorCaseStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class OperatorCaseStatusChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: OperatorCaseStatus
    status: OperatorCaseStatus
    reason: str | None = Field(None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return value.strip()
