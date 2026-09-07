"""Render only from an admitted saved source; return metadata, never PDF bytes."""

from app.schemas.report_read_models import PdfSource
from app.services.report_read_service import source_digest
from app.services.report_pdf_renderer_manifest import load_renderer_manifest
from app.services.report_pdf_errors import PdfError, safe_pdf_code
from app.services.pdf_generator import generate_pdf
from app.services.report_archive_storage import ArchiveStorage


def validate_pdf_limits(data, *, max_bytes, max_pages):
    import fitz

    if not data or len(data) > max_bytes:
        raise PdfError("pdf_render_failed")
    with fitz.open(stream=data, filetype="pdf") as document:
        if not 1 <= len(document) <= max_pages:
            raise PdfError("pdf_render_failed")


def render_pdf_candidate(payload, send):
    phase = "source_validation"

    def entered(value):
        nonlocal phase
        phase = value
        send({"kind": "phase", "phase": value})

    try:
        source = PdfSource.model_validate(payload["source"])
        if source_digest(source) != payload["source_sha256"]:
            raise PdfError("pdf_source_changed")
        _, digest = load_renderer_manifest(payload["manifest_path"])
        if digest != payload["renderer_sha256"]:
            raise PdfError("pdf_renderer_unavailable")
        data = generate_pdf(
            source.content,
            source.title,
            source.prediction_result,
            source.evidence_snapshot,
            report_document=source.report_document,
            renderer_manifest=payload["manifest_path"],
            on_phase=entered,
        )
        from app.core.config import settings

        validate_pdf_limits(
            data,
            max_bytes=settings.REPORT_PDF_MAX_BYTES,
            max_pages=settings.REPORT_PDF_MAX_PAGES,
        )
        entered("storage")
        candidate = ArchiveStorage(payload["archive_root"]).write_candidate(
            payload["object_key"], data
        )
        send(
            {
                "kind": "candidate",
                "phase": "publish",
                "candidate": candidate.model_dump(mode="json"),
            }
        )
    except Exception as error:
        send(
            {
                "kind": "error",
                "phase": phase,
                "code": safe_pdf_code(getattr(error, "code", None)),
            }
        )
