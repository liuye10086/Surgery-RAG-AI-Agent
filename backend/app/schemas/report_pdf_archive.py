from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_object_key(value):
    parts = value.split("/")
    if len(parts) != 4 or parts[0] != "reports" or parts[-1] != "document.pdf":
        raise ValueError("pdf_object_key_invalid")
    if (
        not parts[1].isascii()
        or not parts[1].isdigit()
        or str(int(parts[1])) != parts[1]
        or int(parts[1]) < 1
    ):
        raise ValueError("pdf_object_key_invalid")
    if str(UUID(parts[2])) != parts[2]:
        raise ValueError("pdf_object_key_invalid")
    return value


class PdfCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(max_length=180)
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=64 * 1024 * 1024, strict=True)
    page_count: int = Field(ge=1, le=200, strict=True)
    _key = field_validator("object_key")(validate_object_key)


class PdfClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    attempt_id: int
    lease_token: UUID
    lease_owner: str
    run_deadline: datetime
    source_sha256: str
    renderer_sha256: str
    object_key: str
    _key = field_validator("object_key")(validate_object_key)


class PdfArchiveStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    state: Literal[
        "not_requested", "queued", "rendering", "ready", "failed", "missing", "corrupt"
    ]
    attempt_id: int | None = None
    revision: int
    phase: str | None = None
    code: str | None = None
    message: str
    can_retry: bool = False
    pdf_sha256: str | None = None
    size_bytes: int | None = None
    page_count: int | None = None
    archived_at: datetime | None = None
