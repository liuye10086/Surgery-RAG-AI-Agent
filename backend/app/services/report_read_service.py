"""Validate saved report facts before exposing them to readers or renderers."""

import hashlib
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import AIReport, ReportGenerationJob, ReportPdfArchive
from app.schemas.operator import ReportOut
from app.schemas.report_document import ReportGenerationContext
from app.schemas.synthetic_report_context import SyntheticGenerationContext
from app.schemas.numeric_report import NumericGenerationContext
from app.schemas.numeric_report_v2 import NumericGenerationContextV2
from app.schemas.numeric_report_v3 import NumericGenerationContextV3
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


def _validate_synthetic_saved_identity(row, job, context):
    from app.services.synthetic_report_publication import validate_synthetic_snapshot
    snapshot = row.get("input_snapshot")
    if not isinstance(context, dict):
        raise ValueError("report_identity_mismatch")
    history_numeric = context.get("schema_version") == "numeric_generation_context.v3"
    full_numeric = context.get("schema_version") == "numeric_generation_context.v2"
    unified = history_numeric or full_numeric or context.get("schema_version") == "numeric_generation_context.v1"
    from app.services.numeric_report_publication import validate_numeric_snapshot
    from app.services.numeric_report_v2 import validate_numeric_v2_snapshot
    from app.services.numeric_report_v3 import validate_numeric_v3_snapshot
    validate = validate_numeric_v3_snapshot if history_numeric else validate_numeric_v2_snapshot if full_numeric else validate_numeric_snapshot if unified else validate_synthetic_snapshot
    validate(snapshot, context)
    if (not job or row.get("analysis_type") != ("numeric_prediction" if unified else "synthetic_numeric")
            or snapshot.get("user_id") != row["user_id"]
            or snapshot.get("disease_id") != row.get("disease_id")
            or snapshot.get("generation_batch_id") != row.get("generation_batch_id")
            or snapshot.get("case_id") != job.get("source_case_id")
            or row.get("operator_case_id") not in (None, snapshot.get("case_id"))):
        raise ValueError("report_identity_mismatch")


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
                context_type = (NumericGenerationContextV3 if job["generation_context"].get("schema_version") == "numeric_generation_context.v3" else NumericGenerationContextV2 if job["generation_context"].get("schema_version") == "numeric_generation_context.v2" else NumericGenerationContext if job["generation_context"].get("schema_version") == "numeric_generation_context.v1" else SyntheticGenerationContext if job["generation_context"].get("schema_version")
                                == "synthetic_numeric_generation_context.v1" else ReportGenerationContext)
                context = context_type.model_validate(
                    job["generation_context"]
                )
                data["generation_context"] = context.model_dump(mode="json")
            except (ValueError, TypeError):
                data["context_integrity"] = "invalid"
    history_numeric = ((data["generation_context"] or {}).get("schema_version") == "numeric_generation_context.v3"
        or row.get("generation_fingerprint_version") == "v6"
        or isinstance(row.get("report_document"), dict) and row["report_document"].get("schema_version") == "numeric_report_document.v3")
    full_numeric = ((data["generation_context"] or {}).get("schema_version") == "numeric_generation_context.v2"
        or row.get("generation_fingerprint_version") == "v5"
        or isinstance(row.get("report_document"), dict) and row['report_document'].get('schema_version') == 'numeric_report_document.v2')
    unified = (history_numeric or full_numeric or row.get("analysis_type") == "numeric_prediction"
        or isinstance(row.get("input_snapshot"), dict) and row["input_snapshot"].get("report_kind") == "numeric_prediction"
        or (data["generation_context"] or {}).get("schema_version") == "numeric_generation_context.v1"
        or row.get("generation_fingerprint_version") == "v4")
    synthetic = (unified or row.get("analysis_type") == "synthetic_numeric"
                 or isinstance(row.get("input_snapshot"), dict) and row["input_snapshot"].get("report_kind") == "synthetic_numeric"
                 or isinstance(data["generation_context"], dict) and data["generation_context"].get("schema_version") == "synthetic_numeric_generation_context.v1")
    if row["status"] != "completed":
        if synthetic:
            try:
                if data["context_integrity"] != "valid" or data["snapshot_integrity"] != "valid":
                    raise ValueError("report_identity_mismatch")
                _validate_synthetic_saved_identity(row, job, data["generation_context"])
            except (ValueError, TypeError, KeyError, AttributeError):
                data.update(context_integrity="invalid", snapshot_integrity="invalid", generation_context=None)
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
        if synthetic and row.get("generation_fingerprint_version") != ("v6" if history_numeric else "v5" if full_numeric else "v4" if unified else "v3"):
            raise ValueError("report_identity_mismatch")
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
        if row.get("generation_fingerprint_version") in ("v2", "v3", "v4", "v5", "v6"):
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
        if row.get("generation_fingerprint_version") in ("v3", "v4", "v5", "v6"):
            _validate_synthetic_saved_identity(row, job, data["generation_context"])
            if history_numeric or full_numeric:
                from app.services.numeric_report_v2 import build_numeric_v2_publication
                from app.services.numeric_report_v3 import build_numeric_v3_publication
                build = build_numeric_v3_publication if history_numeric else build_numeric_v2_publication
                saved_publication = build(row['input_snapshot'], row['prediction_result'], row['report_document'])
                status_mismatch = any(row.get(key) != getattr(saved_publication, key) for key in
                    ('evidence_status', 'standard_evidence_status', 'reference_case_status'))
            else:
                status_mismatch = any(row.get(key) != 'not_requested' for key in
                    ('evidence_status', 'standard_evidence_status', 'reference_case_status'))
            if (data["context_integrity"] != "valid"
                    or row["report_document"]["generation_context"] != data["generation_context"]
                    or datetime.fromisoformat(row["report_document"]["identity"]["created_at"]) != row["created_at"]
                    or status_mismatch):
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
