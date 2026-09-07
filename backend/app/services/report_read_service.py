"""Validate saved report facts before exposing them to readers or renderers."""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import AIReport, ReportGenerationJob, ReportPdfArchive
from app.schemas.operator import ReportOut
from app.schemas.report_document import ReportGenerationContext
from app.schemas.report_read_models import PdfSource, ReportReadDetail
from app.services.report_integrity import (
    compute_input_snapshot_sha256,
    verify_report_integrity,
)
from app.services.report_job_repository import context_hash
from app.services.report_saved_identity import saved_report_identity


def restricted_payload(data: dict) -> dict:
    return {
        **data,
        "content": "",
        "prediction_result": {},
        "sources": [],
        "retrieval_meta": {},
        "input_snapshot": None,
        "evidence_snapshot": None,
        "report_document": None,
        "generation_context": None,
        "generation_audit": None,
        "indicators": [],
    }


def _saved_hash_status(value, digest, hash_function):
    if value is None and not digest:
        return "unverifiable"
    if not isinstance(value, dict):
        return "invalid"
    try:
        json.dumps(value, allow_nan=False)
        if not digest:
            return "unverifiable"
        return "valid" if hash_function(value) == digest else "invalid"
    except (ValueError, TypeError, OverflowError):
        return "invalid"


def _validate_saved_containers(row):
    for key, expected, nullable in (
        ("content", str, False),
        ("sources", list, False),
        ("prediction_result", dict, True),
        ("retrieval_meta", dict, False),
        ("indicators", list, True),
        ("input_snapshot", dict, True),
        ("evidence_snapshot", dict, True),
        ("report_document", dict, True),
    ):
        value = row.get(key)
        if value is None and (nullable or key not in row):
            continue
        if not isinstance(value, expected):
            raise ValueError("integrity_payload_invalid")
        json.dumps(value, allow_nan=False)
        if expected is list and any(not isinstance(item, dict) for item in value):
            raise ValueError("integrity_payload_invalid")


def project_report(row, job=None):
    data = {key: value for key, value in row.items() if key in ReportOut.model_fields}
    identity = saved_report_identity(row["id"], row.get("input_snapshot"))
    data.update(
        title=identity.title,
        query=identity.title,
        anonymous_case_code=identity.anonymous_case_code,
    )
    if row.get("error_message"):
        from app.services.report_generation_errors import MESSAGES, safe_code

        data["error_message"] = MESSAGES[safe_code(row["error_message"])]
    for key, default in (
        ("prediction_result", {}),
        ("indicators", []),
        ("sources", []),
        ("retrieval_meta", {}),
    ):
        if data.get(key) is None:
            data[key] = default
    data.update(
        snapshot_integrity=_saved_hash_status(
            row.get("input_snapshot"),
            row.get("input_snapshot_sha256"),
            compute_input_snapshot_sha256,
        ),
        context_integrity="unverifiable",
        generation_context=None,
        generation_audit=None,
    )
    if job:
        data["context_integrity"] = _saved_hash_status(
            job.get("generation_context"), job.get("context_sha256"), context_hash
        )
        if data["context_integrity"] == "valid":
            try:
                context = ReportGenerationContext.model_validate(
                    job["generation_context"]
                )
                data["generation_context"] = context.model_dump(mode="json")
            except (ValueError, TypeError):
                data["context_integrity"] = "invalid"
    if row["status"] != "completed":
        snapshot, context = data.get("input_snapshot"), data["generation_context"]
        data = restricted_payload(data)
        data.update(
            publication_status="not_published",
            integrity_status="unverifiable",
            integrity_reason_code="report_not_published",
        )
        if data["snapshot_integrity"] == "valid":
            data["input_snapshot"] = snapshot
        data["generation_context"] = context
        return ReportReadDetail.model_validate(data)
    try:
        _validate_saved_containers(row)
        result = verify_report_integrity(
            row.get("input_snapshot"),
            row.get("input_snapshot_sha256"),
            row.get("generation_fingerprint"),
            row.get("prediction_result"),
            row.get("content"),
            row.get("evidence_snapshot"),
            row.get("evidence_snapshot_sha256"),
            saved_sources=row.get("sources", []),
            report_document=row.get("report_document"),
            report_document_sha256=row.get("report_document_sha256"),
            generation_fingerprint_version=row.get("generation_fingerprint_version"),
        )
        data.update(
            integrity_status=result.status, integrity_reason_code=result.reason_code
        )
        if result.status == "invalid":
            raise ValueError(result.reason_code)
        if row.get("generation_fingerprint_version") == "v2":
            document_identity = row["report_document"]["identity"]
            snapshot = row["input_snapshot"]
            if (
                document_identity["report_id"] != row["id"]
                or document_identity["batch_id"] != row.get("generation_batch_id")
                or document_identity["batch_id"] != snapshot.get("generation_batch_id")
                or document_identity["disease_code"] != snapshot.get("disease_code")
                or document_identity["anonymous_case_code"]
                != identity.anonymous_case_code
            ):
                raise ValueError("report_identity_mismatch")
        data["publication_status"] = "published"
        return ReportReadDetail.model_validate(data)
    except (ValueError, TypeError, KeyError, OverflowError):
        data = restricted_payload(data)
        data.update(
            publication_status="invalid",
            integrity_status="invalid",
            integrity_reason_code="report_integrity_failed",
        )
        return ReportReadDetail.model_validate(data)


def read_owned_report(db, user_id: int, report_id: int):
    row = (
        db.execute(
            select(AIReport.__table__).where(
                AIReport.id == report_id,
                AIReport.user_id == user_id,
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, detail="报告不存在")
    job = (
        db.execute(
            select(ReportGenerationJob.__table__).where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.user_id == user_id,
            )
        )
        .mappings()
        .first()
    )
    detail = project_report(dict(row), dict(job) if job else None)
    detail.download_count += (
        db.execute(
            select(ReportPdfArchive.delivery_count).where(
                ReportPdfArchive.report_id == report_id
            )
        ).scalar_one_or_none()
        or 0
    )
    if (
        job
        and detail.context_integrity == "valid"
        and detail.publication_status != "invalid"
    ):
        from app.services.report_generation_audit import read_generation_audit

        try:
            detail.generation_audit = read_generation_audit(
                db, dict(job), row["generation_batch_id"]
            ).model_dump(mode="json")
        except (ValueError, TypeError, KeyError):
            detail.generation_audit = None
    return detail


def build_pdf_source(detail):
    if (
        detail.status != "completed"
        or detail.publication_status != "published"
        or detail.integrity_status == "invalid"
        or not detail.content
    ):
        raise ValueError("report_not_exportable")
    return PdfSource(
        report_id=detail.id,
        batch_id=detail.generation_batch_id,
        title=detail.title,
        anonymous_case_code=detail.anonymous_case_code,
        integrity_status=detail.integrity_status,
        generation_fingerprint_version=detail.generation_fingerprint_version,
        generation_fingerprint=detail.generation_fingerprint,
        report_document_sha256=detail.report_document_sha256,
        content=detail.content,
        prediction_result=detail.prediction_result,
        input_snapshot=detail.input_snapshot,
        evidence_snapshot=detail.evidence_snapshot,
        report_document=detail.report_document,
    )


def source_digest(source: PdfSource) -> str:
    encoded = json.dumps(
        source.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
