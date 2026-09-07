from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.api.deps import require_ai_operator
from app.db.session import get_db
from app.db.models import User
from app.schemas.report_pdf_archive import PdfArchiveStatus
from app.services.report_pdf_errors import PdfError
from app.services.report_pdf_archive_service import (
    prepare_pdf_archive,
    read_pdf_archive_status,
)

router = APIRouter(prefix="/operator/reports", tags=["operator"])


class EmptyPdfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def pdf_http_error(error):
    return HTTPException(
        error.status_code,
        detail={"code": error.code, "message": error.message},
        headers={"Retry-After": "10"} if error.status_code == 429 else None,
    )


@router.get("/{report_id}/pdf-archive", response_model=PdfArchiveStatus)
def get_pdf_archive(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return read_pdf_archive_status(db, current_user.id, report_id)
    except PdfError as error:
        raise pdf_http_error(error)


def _prepare(report_id, response, key, db, user, retry):
    try:
        result = prepare_pdf_archive(db, user.id, report_id, key, retry=retry)
        response.status_code = 202 if result.state in ("queued", "rendering") else 200
        return result
    except PdfError as error:
        raise pdf_http_error(error)


@router.post("/{report_id}/pdf-archive", response_model=PdfArchiveStatus)
def prepare(
    report_id: int,
    response: Response,
    payload: EmptyPdfRequest = EmptyPdfRequest(),
    idempotency_key: str | None = Header(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    return _prepare(report_id, response, idempotency_key, db, current_user, False)


@router.post("/{report_id}/pdf-archive/retry", response_model=PdfArchiveStatus)
def retry(
    report_id: int,
    response: Response,
    payload: EmptyPdfRequest = EmptyPdfRequest(),
    idempotency_key: str | None = Header(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    return _prepare(report_id, response, idempotency_key, db, current_user, True)
