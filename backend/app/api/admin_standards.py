"""Administrator API for versioned reference standards."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.models import (
    Document,
    ReferenceStandard,
    ReferenceStandardVersion,
    StandardParseCandidate,
    StandardRule,
    StandardSegment,
)
from app.db.session import get_db
from app.schemas.standard import (
    RuleOut,
    RulePatch,
    StandardChangeRequest,
    StandardCreate,
    StandardOut,
    StandardParseCandidateOut,
    StandardSegmentOut,
    StandardVersionCreate,
    StandardVersionOut,
    ValidationReport,
)
from app.services.standard_lifecycle import publish_approved_version, update_draft_rule
from app.services.standard_parser import parse_standard_docx
from app.services.standard_validation import validate_version_rules


router = APIRouter(prefix="", tags=["admin-standard"])


def _hash_file(path: str | None) -> str:
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail="标准文件不存在")
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version_or_404(db: Session, version_id: int) -> ReferenceStandardVersion:
    version = db.query(ReferenceStandardVersion).filter(ReferenceStandardVersion.id == version_id).first()
    if version is None:
        raise HTTPException(status_code=404, detail="标准版本不存在")
    return version


@router.get("/admin/reference-standards", response_model=list[StandardOut])
def list_standards(admin=Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(ReferenceStandard).order_by(ReferenceStandard.id).all()


@router.post("/admin/reference-standards", response_model=StandardOut, status_code=status.HTTP_201_CREATED)
def create_standard(payload: StandardCreate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(ReferenceStandard).filter(ReferenceStandard.disease_id == payload.disease_id).first():
        raise HTTPException(status_code=409, detail="该疾病已有标准集合")
    standard = ReferenceStandard(disease_id=payload.disease_id, name=payload.name, description=payload.description)
    db.add(standard)
    db.commit()
    db.refresh(standard)
    return standard


@router.get("/admin/reference-standards/{standard_id}", response_model=StandardOut)
def get_standard(standard_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    standard = db.query(ReferenceStandard).filter(ReferenceStandard.id == standard_id).first()
    if standard is None:
        raise HTTPException(status_code=404, detail="标准集合不存在")
    return standard


@router.post("/admin/reference-standards/{standard_id}/versions", response_model=StandardVersionOut, status_code=status.HTTP_201_CREATED)
def create_version(standard_id: int, payload: StandardVersionCreate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    standard = db.query(ReferenceStandard).filter(ReferenceStandard.id == standard_id).first()
    document = db.query(Document).filter(Document.id == payload.document_id).first()
    if standard is None:
        raise HTTPException(status_code=404, detail="标准集合不存在")
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if (document.file_type or "").lower() != "docx":
        raise HTTPException(status_code=422, detail="标准源文件只支持 DOCX")
    content_hash = _hash_file(document.file_path)
    duplicate = db.query(ReferenceStandardVersion).filter(
        ReferenceStandardVersion.standard_id == standard_id,
        ReferenceStandardVersion.content_hash == content_hash,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="同一标准和文件内容不能重复创建版本")
    version = ReferenceStandardVersion(
        standard_id=standard_id,
        document_id=document.id,
        version_label=payload.version_label,
        content_hash=content_hash,
        parser_version=payload.parser_version,
        created_by=getattr(admin, "id", None),
        supersedes_version_id=standard.current_version_id,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


@router.get("/admin/reference-standard-versions/{version_id}", response_model=StandardVersionOut)
def get_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    return _version_or_404(db, version_id)


@router.post("/admin/reference-standard-versions/{version_id}/parse")
def parse_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    version = _version_or_404(db, version_id)
    if version.status not in {"draft", "review"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已批准或已退役版本不可重新解析")
    if (version.document.file_type or "").lower() != "docx":
        raise HTTPException(status_code=422, detail="标准源文件只支持 DOCX")
    parsed = parse_standard_docx(version.document.file_path, parser_version=version.parser_version)
    version.segments.clear()
    for segment in parsed.segments:
        db.add(StandardSegment(
            version_id=version.id,
            section_title=segment.section_title,
            paragraph_index=segment.paragraph_index,
            table_index=segment.table_index,
            row_index=segment.row_index,
            column_index=segment.column_index,
            raw_text=segment.raw_text,
            segment_type=segment.segment_type,
            parse_status="parsed",
            source_metadata=segment.source_metadata,
        ))
    version.status = "draft"
    db.commit()
    return {"version_id": version.id, "segments": len(parsed.segments), "candidates": len(parsed.rule_candidates)}


@router.post("/admin/reference-standard-versions/{version_id}/submit-review", response_model=StandardVersionOut)
def submit_review(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    version = _version_or_404(db, version_id)
    if version.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有 draft 版本可以提交审核")
    version.status = "review"
    db.commit()
    db.refresh(version)
    return version


@router.post("/admin/reference-standard-versions/{version_id}/approve", response_model=StandardVersionOut)
def approve_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return publish_approved_version(db, getattr(admin, "id", 0), version_id).version
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_409_CONFLICT if "review" not in message and "发布" not in message else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=message) from exc


@router.post("/admin/reference-standard-versions/{version_id}/retire", response_model=StandardVersionOut)
def retire_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    version = _version_or_404(db, version_id)
    if version.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有 approved 版本可以退役")
    version.status = "retired"
    db.commit()
    db.refresh(version)
    return version


@router.get("/admin/reference-standard-versions/{version_id}/segments", response_model=list[StandardSegmentOut])
def list_segments(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    _version_or_404(db, version_id)
    return db.query(StandardSegment).filter(StandardSegment.version_id == version_id).order_by(StandardSegment.id).all()


@router.get("/admin/reference-standard-versions/{version_id}/rules", response_model=list[RuleOut])
def list_rules(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    _version_or_404(db, version_id)
    return db.query(StandardRule).filter(StandardRule.version_id == version_id).order_by(StandardRule.id).all()


@router.patch("/admin/reference-standard-rules/{rule_id}", response_model=RuleOut)
def patch_rule(rule_id: int, payload: RulePatch, reason: StandardChangeRequest, admin=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return update_draft_rule(db, getattr(admin, "id", 0), rule_id, payload, reason.reason)
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_409_CONFLICT if "不可编辑" in message else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=message) from exc


@router.get("/admin/reference-standard-versions/{version_id}/validation", response_model=ValidationReport)
def validate_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    version = _version_or_404(db, version_id)
    return validate_version_rules(list(version.rules or []))


@router.get("/admin/reference-standard-versions/{version_id}/candidates", response_model=list[StandardParseCandidateOut])
def list_candidates(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    _version_or_404(db, version_id)
    return db.query(StandardParseCandidate).filter(StandardParseCandidate.version_id == version_id).order_by(StandardParseCandidate.id).all()
