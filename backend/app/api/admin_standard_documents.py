"""Administrator API for independently stored standard source documents."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.db.models import ReferenceStandardVersion, StandardDocument
from app.db.session import get_db
from app.schemas.standard_document import StandardDocumentOut
from app.services.standard_document_storage import (
    StandardFileRecoverySnapshot,
    StoredStandardFile,
    delete_standard_file,
    restore_standard_file,
    save_standard_upload,
    snapshot_standard_file,
    validate_standard_docx,
)


router = APIRouter(prefix="", tags=["admin-standard-documents"])


def standard_document_to_out(document: StandardDocument) -> StandardDocumentOut:
    version = document.version
    standard = version.standard if version else None
    return StandardDocumentOut(
        id=document.id,
        title=document.title,
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        content_hash=document.content_hash,
        uploaded_by=document.uploaded_by,
        created_at=document.created_at,
        is_locked=version is not None,
        standard_id=getattr(standard, "id", None),
        standard_name=getattr(standard, "name", None),
        version_id=getattr(version, "id", None),
        version_label=getattr(version, "version_label", None),
    )


def _remove_new_file(stored: StoredStandardFile | None) -> None:
    if stored is not None:
        delete_standard_file(stored.path)


@router.post(
    "/admin/standard-documents/upload",
    response_model=StandardDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_standard_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        validate_standard_docx(file.filename)
        stored = save_standard_upload(file)
    except ValueError as exc:
        error_status = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if "DOCX" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=error_status, detail=str(exc)) from exc

    try:
        duplicate = (
            db.query(StandardDocument)
            .filter(StandardDocument.content_hash == stored.content_hash)
            .first()
        )
        if duplicate is not None:
            _remove_new_file(stored)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="相同内容的标准文件已上传",
            )

        normalized_title = title.strip() if title else ""
        document = StandardDocument(
            title=normalized_title or file.filename,
            filename=file.filename or "unnamed.docx",
            file_path=stored.path,
            file_type="docx",
            file_size=stored.file_size,
            content_hash=stored.content_hash,
            uploaded_by=getattr(admin, "id", None),
        )
        db.add(document)
        db.flush()
        db.refresh(document)
        output = standard_document_to_out(document)
        db.commit()
        return output
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        _remove_new_file(stored)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="相同内容的标准文件已上传",
        ) from exc
    except Exception as exc:
        db.rollback()
        _remove_new_file(stored)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="标准文件保存失败",
        ) from exc


@router.get("/admin/standard-documents", response_model=list[StandardDocumentOut])
def list_standard_documents(
    available_only: bool = Query(False),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(StandardDocument).options(
        joinedload(StandardDocument.version).joinedload(ReferenceStandardVersion.standard)
    )
    if available_only:
        query = query.filter(StandardDocument.version == None)  # noqa: E711
    documents = query.order_by(StandardDocument.created_at.desc()).all()
    return [standard_document_to_out(document) for document in documents]


@router.delete(
    "/admin/standard-documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_standard_document(
    document_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    document = db.query(StandardDocument).filter(StandardDocument.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="标准文件不存在")
    if document.version is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="标准文件已关联版本，不可删除",
        )

    recovery_snapshot: StandardFileRecoverySnapshot | None = None
    try:
        db.delete(document)
        db.flush()
        recovery_snapshot = snapshot_standard_file(document.file_path)
        delete_standard_file(document.file_path)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="标准文件删除失败",
        ) from exc

    try:
        db.commit()
    except Exception as commit_exc:
        compensation_error: Exception | None = None
        try:
            db.rollback()
        except Exception as rollback_exc:
            compensation_error = rollback_exc
        try:
            restore_standard_file(recovery_snapshot)
        except Exception as restore_exc:
            compensation_error = restore_exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="标准文件删除失败",
        ) from (compensation_error or commit_exc)

    return None
