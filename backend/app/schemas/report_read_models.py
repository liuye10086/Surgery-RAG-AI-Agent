from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.operator import ReportOut

Integrity = Literal["valid", "invalid", "unverifiable"]


class ReportReadDetail(ReportOut):
    publication_status: Literal["published", "not_published", "invalid"]
    snapshot_integrity: Integrity
    context_integrity: Integrity
    generation_context: dict | None = None
    generation_audit: dict | None = None


class PdfSource(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["pdf_source.v1"] = "pdf_source.v1"
    report_id: int = Field(gt=0)
    batch_id: str | None
    title: str
    anonymous_case_code: str | None
    integrity_status: Integrity
    generation_fingerprint_version: str | None
    generation_fingerprint: str | None
    report_document_sha256: str | None
    content: str
    prediction_result: dict
    input_snapshot: dict | None
    evidence_snapshot: dict | None
    report_document: dict | None
