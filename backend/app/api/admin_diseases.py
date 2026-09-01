"""Administrator-owned disease catalog management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.models import Disease
from app.db.session import get_db
from app.schemas.prediction import (
    AdminDiseaseOut,
    DiseaseCreate,
    DiseaseUpdate,
    DiseaseUsageCountsOut,
)
from app.services.disease_catalog import (
    DiseaseCapabilityMissingError,
    disease_usage_counts,
    require_disease_capability,
)


router = APIRouter(prefix="/admin/diseases", tags=["admin-diseases"])

DISEASE_REFERENCE_FKS = {
    "fk_operator_cases_disease",
    "fk_case_records_disease",
    "fk_ai_reports_disease",
    "reference_standards_disease_id_fkey",
}


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


def _to_admin_out(db: Session, disease: Disease) -> AdminDiseaseOut:
    counts = disease_usage_counts(db, disease.id)
    return AdminDiseaseOut(
        id=disease.id,
        code=disease.code,
        name=disease.name,
        description=disease.description,
        operator_enabled=disease.operator_enabled,
        created_at=disease.created_at,
        usage_counts=DiseaseUsageCountsOut(
            operator_cases=counts.operator_cases,
            case_records=counts.case_records,
            ai_reports=counts.ai_reports,
            reference_standards=counts.reference_standards,
        ),
        can_delete=counts.total == 0,
    )


def _disease_or_404(db: Session, disease_id: int, *, for_update: bool = False) -> Disease:
    query = db.query(Disease).filter(Disease.id == disease_id)
    if for_update:
        query = query.with_for_update()
    disease = query.first()
    if disease is None:
        raise HTTPException(status_code=404, detail="疾病不存在")
    return disease


@router.get("", response_model=list[AdminDiseaseOut])
def list_diseases(admin=Depends(require_admin), db: Session = Depends(get_db)):
    diseases = db.query(Disease).order_by(Disease.id).all()
    return [_to_admin_out(db, disease) for disease in diseases]


@router.post("", response_model=AdminDiseaseOut, status_code=201)
def create_disease(
    payload: DiseaseCreate,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    code = payload.code.strip()
    name = payload.name.strip()
    if db.query(Disease.id).filter(Disease.code == code).first():
        raise HTTPException(status_code=409, detail="疾病代码已存在")
    if db.query(Disease.id).filter(Disease.name == name).first():
        raise HTTPException(status_code=409, detail="疾病名称已存在")
    disease = Disease(
        code=code,
        name=name,
        description=payload.description,
        operator_enabled=False,
    )
    db.add(disease)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="疾病代码或名称已存在") from exc
    db.refresh(disease)
    return _to_admin_out(db, disease)


@router.put("/{disease_id}", response_model=AdminDiseaseOut)
def update_disease(
    disease_id: int,
    payload: DiseaseUpdate,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    disease = _disease_or_404(db, disease_id, for_update=True)
    if payload.operator_enabled:
        try:
            require_disease_capability(disease.code)
        except DiseaseCapabilityMissingError as exc:
            raise HTTPException(
                status_code=422,
                detail="该疾病尚未配置预测能力，不能启用",
            ) from exc
    if payload.name is not None:
        name = payload.name.strip()
        duplicate = db.query(Disease.id).filter(
            Disease.name == name,
            Disease.id != disease.id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="疾病名称已存在")
        disease.name = name
    if "description" in payload.model_fields_set:
        disease.description = payload.description
    if payload.operator_enabled is not None:
        disease.operator_enabled = payload.operator_enabled
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="疾病名称已存在") from exc
    db.refresh(disease)
    return _to_admin_out(db, disease)


@router.delete("/{disease_id}", status_code=204)
def delete_disease(
    disease_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    disease = _disease_or_404(db, disease_id, for_update=True)
    if disease_usage_counts(db, disease.id).total:
        raise HTTPException(status_code=409, detail="该疾病已被业务数据引用，不能删除")
    db.delete(disease)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _integrity_constraint_name(exc) in DISEASE_REFERENCE_FKS:
            raise HTTPException(
                status_code=409,
                detail="该疾病已被业务数据引用，不能删除",
            ) from exc
        raise
    return Response(status_code=204)
