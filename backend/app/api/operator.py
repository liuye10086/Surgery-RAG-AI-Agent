"""AI 操作者纵向预测报告、病例和标准数据 API 路由。"""

import logging
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_ai_operator
from app.db.models import (
    AIReport,
    CaseRecord,
    Chunk,
    Department,
    Disease,
    Document,
    ReferenceRange,
    ReferenceStandard,
    User,
)
from app.db.session import get_db
from app.schemas.operator import (
    ReportListOut,
    ReportListItem,
    ReportOut,
)
from app.schemas.prediction import (
    CaseRecordIn,
    CaseRecordOut,
    DiseaseCreate,
    DiseaseOut,
    DiseaseUpdate,
    ReferenceRangeOut,
)
from app.schemas.progression import (
    LongitudinalPredictRequest,
    ProgressionPredictionOut,
)
from app.schemas.longitudinal_case import (
    OperatorCaseCreate,
    OperatorCaseListOut,
    OperatorCaseOut,
    OperatorCaseUpdate,
    VisitCreate,
    VisitReplaceRequest,
    VisitOut,
    VisitUpdate,
)
from app.schemas.longitudinal_report import LongitudinalReportRequest
from app.services.pdf_generator import generate_pdf
from app.services.progression_engine import predict_progression
from app.services.longitudinal_case_service import (
    CaseNotFoundError,
    DuplicateVisitDateError,
    DiseaseNotFoundError,
    VisitLimitError,
    VisitNotFoundError,
    add_visit,
    create_operator_case,
    delete_operator_case,
    delete_visit,
    get_operator_case,
    list_operator_cases,
    update_operator_case,
    update_visit,
    replace_visits,
    build_input_snapshot,
)
from app.services.disease_progression import get_progression_adapter
from app.services.longitudinal_report_generator import generate_longitudinal_report
from app.services.longitudinal_model_registry import load_model_registry
from app.services.longitudinal_evidence import (
    build_reference_range_sources,
    mark_synthetic_source,
    select_similar_longitudinal_cases,
)

logger = logging.getLogger(__name__)
REFERENCE_STANDARD_DISEASE_FK = "reference_standards_disease_id_fkey"


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


router = APIRouter(prefix="/operator", tags=["operator"])

_PROGRESSION_DATASETS = {
    "脂肪肝": "fatty_liver",
    "阿尔茨海默病": "ad",
}


def _verify_report_owner(report: AIReport, current_user: User) -> None:
    """校验报告归属权。admin 也只能查看/操作自己创建的报告。"""
    if report.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="报告不存在",
        )


@router.post(
    "/progression-predictions",
    response_model=ProgressionPredictionOut,
)
def create_progression_prediction(
    request: LongitudinalPredictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """Return a synchronous longitudinal risk estimate without persistence."""
    disease = db.query(Disease).filter(Disease.id == request.disease_id).first()
    if disease is None:
        raise HTTPException(status_code=422, detail="疾病不存在")
    dataset = _PROGRESSION_DATASETS.get(disease.name)
    if dataset is None:
        raise HTTPException(status_code=422, detail="该疾病尚无可用进展预测模型")

    visits = [
        {
            "visit_date": visit.visit_date.isoformat(),
            "indicators": [indicator.model_dump() for indicator in visit.indicators],
        }
        for visit in request.visits
    ]
    try:
        return predict_progression(dataset, visits)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# /operator/longitudinal-cases — 操作者自有纵向病例与访视
# ---------------------------------------------------------------------------


def _longitudinal_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (CaseNotFoundError, VisitNotFoundError)):
        # Do not reveal whether another operator owns the resource.
        return HTTPException(status_code=404, detail="病例或访视不存在")
    if isinstance(exc, DiseaseNotFoundError):
        return HTTPException(status_code=422, detail="疾病不存在")
    if isinstance(exc, (DuplicateVisitDateError, VisitLimitError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/longitudinal-cases", response_model=OperatorCaseOut, status_code=201)
def create_longitudinal_case(
    payload: OperatorCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return create_operator_case(db, current_user.id, payload)
    except (DiseaseNotFoundError, CaseNotFoundError) as exc:
        raise _longitudinal_error(exc) from exc


@router.get("/longitudinal-cases", response_model=OperatorCaseListOut)
def list_longitudinal_cases(
    disease_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    cases = list_operator_cases(db, current_user.id, disease_id=disease_id)
    return OperatorCaseListOut(cases=cases, total=len(cases))


@router.get("/longitudinal-cases/{case_id}", response_model=OperatorCaseOut)
def get_longitudinal_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return get_operator_case(db, current_user.id, case_id)
    except CaseNotFoundError as exc:
        raise _longitudinal_error(exc) from exc


@router.put("/longitudinal-cases/{case_id}", response_model=OperatorCaseOut)
def update_longitudinal_case(
    case_id: int,
    payload: OperatorCaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return update_operator_case(db, current_user.id, case_id, payload)
    except (CaseNotFoundError, DiseaseNotFoundError) as exc:
        raise _longitudinal_error(exc) from exc


@router.delete("/longitudinal-cases/{case_id}", status_code=204)
def delete_longitudinal_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        delete_operator_case(db, current_user.id, case_id)
    except CaseNotFoundError as exc:
        raise _longitudinal_error(exc) from exc
    return None


@router.post(
    "/longitudinal-cases/{case_id}/visits",
    response_model=VisitOut,
    status_code=201,
)
def create_longitudinal_visit(
    case_id: int,
    payload: VisitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return add_visit(db, current_user.id, case_id, payload)
    except (CaseNotFoundError, DuplicateVisitDateError, VisitLimitError) as exc:
        raise _longitudinal_error(exc) from exc


@router.put(
    "/longitudinal-cases/{case_id}/visits",
    response_model=list[VisitOut],
)
def replace_longitudinal_visits(
    case_id: int,
    payload: VisitReplaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return replace_visits(db, current_user.id, case_id, payload.visits)
    except (
        CaseNotFoundError,
        DuplicateVisitDateError,
        VisitLimitError,
    ) as exc:
        raise _longitudinal_error(exc) from exc


@router.put(
    "/longitudinal-cases/{case_id}/visits/{visit_id}",
    response_model=VisitOut,
)
def update_longitudinal_visit(
    case_id: int,
    visit_id: int,
    payload: VisitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return update_visit(db, current_user.id, case_id, visit_id, payload)
    except (
        CaseNotFoundError,
        VisitNotFoundError,
        DuplicateVisitDateError,
    ) as exc:
        raise _longitudinal_error(exc) from exc


@router.delete(
    "/longitudinal-cases/{case_id}/visits/{visit_id}",
    status_code=204,
)
def delete_longitudinal_visit(
    case_id: int,
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        delete_visit(db, current_user.id, case_id, visit_id)
    except (CaseNotFoundError, VisitNotFoundError) as exc:
        raise _longitudinal_error(exc) from exc
    return None


@router.post("/longitudinal-cases/{case_id}/reports")
async def create_longitudinal_report(
    case_id: int,
    request: LongitudinalReportRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        case = get_operator_case(db, current_user.id, case_id)
    except CaseNotFoundError as exc:
        raise _longitudinal_error(exc) from exc
    try:
        adapter = get_progression_adapter({"脂肪肝": "fatty_liver", "阿尔茨海默病": "ad"}.get(case.disease.name, ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    visits = [
        {"visit_date": visit.visit_date.isoformat(), "indicators": visit.indicators or [], "notes": visit.notes}
        for visit in sorted(case.visits, key=lambda item: item.visit_date)
    ]
    indicator_names = sorted({
        str(indicator.get("name", "")).strip().lower()
        for visit in visits
        for indicator in visit["indicators"]
        if str(indicator.get("name", "")).strip()
    })
    try:
        sources = build_reference_range_sources(db, indicator_names, case.sex, disease_id=case.disease_id)
        sources.extend(select_similar_longitudinal_cases(db, case.disease_id, visits, adapter))
        sources = [mark_synthetic_source(source) for source in sources]
    except Exception:
        logger.exception("Longitudinal evidence selection failed for case_id=%s", case.id)
        sources = []
    options = (request or LongitudinalReportRequest()).model_options
    snapshot = build_input_snapshot(case, case.visits, options)
    report = AIReport(user_id=current_user.id, operator_case_id=case.id, disease_id=case.disease_id, query=case.patient_label, title=f"{case.patient_label}纵向进展预测报告", indicators=[], analysis_type="longitudinal_predictive", status="generating", input_snapshot=snapshot)
    db.add(report)
    db.commit()
    db.refresh(report)
    model_registry = load_model_registry(adapter.dataset)
    return StreamingResponse(generate_longitudinal_report(db, report.id, snapshot, visits, adapter, model_registry=model_registry, sources=sources), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# GET /operator/reports — 列出报告
# ---------------------------------------------------------------------------


@router.get("/reports", response_model=ReportListOut)
def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    analysis_type: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """列出当前用户创建的报告，按创建时间倒序，可按 analysis_type 过滤。"""
    q = db.query(AIReport).filter(AIReport.user_id == current_user.id)
    if analysis_type is not None:
        q = q.filter(AIReport.analysis_type == analysis_type)
    total = q.count()
    reports = (
        q.order_by(AIReport.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return ReportListOut(
        reports=[ReportListItem.model_validate(r) for r in reports],
        total=total,
    )


# ---------------------------------------------------------------------------
# GET /operator/reports/{id} — 报告详情
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """获取单个报告详情（含完整 content）。"""
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在"
        )
    _verify_report_owner(report, current_user)
    return report


# ---------------------------------------------------------------------------
# DELETE /operator/reports/{id} — 删除报告
# ---------------------------------------------------------------------------


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """删除报告（仅创建者可删除）。"""
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在"
        )
    _verify_report_owner(report, current_user)
    db.delete(report)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# GET /operator/reports/{id}/download — 下载 PDF
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}/download")
def download_report_pdf(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """下载报告的 PDF 版本。

    仅 completed 状态的报告可下载。
    每次下载自增 download_count。
    """
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在"
        )
    _verify_report_owner(report, current_user)

    if report.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"报告状态为 '{report.status}'，仅已完成报告可下载",
        )

    if not report.content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="报告内容为空，无法生成 PDF",
        )

    title = report.title or "分析报告"

    try:
        pdf_bytes = generate_pdf(report.content, title)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    # 更新下载计数
    report.download_count = (report.download_count or 0) + 1
    db.commit()

    # 构建安全 Content-Disposition（RFC 5987：ASCII fallback + UTF-8 编码文件名）
    safe_filename = f"report-{report_id}.pdf"
    clean_title = title.replace("\r", "").replace("\n", "").replace('"', "").strip()
    encoded_title = urllib.parse.quote(f"{clean_title}.pdf", safe="")
    content_disposition = (
        f'attachment; filename="{safe_filename}"; '
        f"filename*=UTF-8''{encoded_title}"
    )

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition},
    )


# ---------------------------------------------------------------------------
# 疾病 CRUD（纵向预测数据层）
# ---------------------------------------------------------------------------


@router.post("/diseases", response_model=DiseaseOut)
def create_disease(
    payload: DiseaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    if db.query(Disease).filter(Disease.name == payload.name).first():
        raise HTTPException(status_code=409, detail=f"疾病「{payload.name}」已存在")
    d = Disease(name=payload.name, description=payload.description)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _disease_to_out(d: Disease, case_count: int) -> DiseaseOut:
    """显式构造 DiseaseOut。

    注意：Pydantic v2 的 `model_validate` 没有 `update` 参数，
    `model_validate(d, update={...})` 会抛 TypeError。必须显式传值构造。
    """
    return DiseaseOut(
        id=d.id,
        name=d.name,
        description=d.description,
        case_count=case_count,
        created_at=d.created_at,
    )


@router.get("/diseases", response_model=list[DiseaseOut])
def list_diseases(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    diseases = db.query(Disease).order_by(Disease.id).all()
    counts = dict(
        db.query(CaseRecord.disease_id, func.count(CaseRecord.id))
        .group_by(CaseRecord.disease_id)
        .all()
    )
    return [_disease_to_out(d, counts.get(d.id, 0)) for d in diseases]


@router.put("/diseases/{disease_id}", response_model=DiseaseOut)
def update_disease(
    disease_id: int,
    payload: DiseaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    d = db.query(Disease).filter(Disease.id == disease_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="疾病不存在")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="疾病名称不能为空")
        if (
            db.query(Disease)
            .filter(Disease.name == name, Disease.id != disease_id)
            .first()
        ):
            raise HTTPException(status_code=409, detail=f"疾病「{name}」已存在")
        d.name = name
    if payload.description is not None:
        d.description = payload.description
    db.commit()
    db.refresh(d)
    return d


@router.delete("/diseases/{disease_id}", status_code=204)
def delete_disease(
    disease_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    d = (
        db.query(Disease)
        .filter(Disease.id == disease_id)
        .with_for_update()
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="疾病不存在")
    if db.query(CaseRecord).filter(CaseRecord.disease_id == disease_id).count():
        raise HTTPException(status_code=409, detail="该疾病下存在病例，请先删除病例")
    if (
        db.query(ReferenceStandard)
        .filter(ReferenceStandard.disease_id == disease_id)
        .first()
    ):
        raise HTTPException(status_code=409, detail="该疾病已关联参考标准，不能删除")
    db.delete(d)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _integrity_constraint_name(exc) == REFERENCE_STANDARD_DISEASE_FK:
            raise HTTPException(
                status_code=409,
                detail="该疾病已关联参考标准，不能删除",
            ) from exc
        raise
    return None


# ---------------------------------------------------------------------------
# 病例 CRUD（纵向预测数据层）
# ---------------------------------------------------------------------------


def _get_case_or_404(db: Session, case_id: int) -> CaseRecord:
    c = db.query(CaseRecord).filter(CaseRecord.id == case_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="病例不存在")
    return c


@router.post("/cases", response_model=CaseRecordOut)
def create_case(
    payload: CaseRecordIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    if not db.query(Disease).filter(Disease.id == payload.disease_id).first():
        raise HTTPException(status_code=422, detail="疾病不存在")
    c = CaseRecord(
        disease_id=payload.disease_id,
        patient_label=payload.patient_label,
        indicators=[i.model_dump() for i in payload.indicators],
        confirmed=payload.confirmed,
        case_metadata=payload.metadata,  # ORM 属性名是 case_metadata
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("/cases")
def list_cases(
    disease_id: int | None = Query(None),
    confirmed: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    q = db.query(CaseRecord)
    if disease_id is not None:
        q = q.filter(CaseRecord.disease_id == disease_id)
    if confirmed is not None:
        q = q.filter(CaseRecord.confirmed.is_(confirmed))
    total = q.count()
    items = (
        q.order_by(CaseRecord.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": [CaseRecordOut.model_validate(c) for c in items]}


@router.put("/cases/{case_id}", response_model=CaseRecordOut)
def update_case(
    case_id: int,
    payload: CaseRecordIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    c = _get_case_or_404(db, case_id)
    if not db.query(Disease).filter(Disease.id == payload.disease_id).first():
        raise HTTPException(status_code=422, detail="疾病不存在")
    c.disease_id = payload.disease_id
    c.patient_label = payload.patient_label
    c.indicators = [i.model_dump() for i in payload.indicators]
    c.confirmed = payload.confirmed
    c.case_metadata = payload.metadata  # ORM 属性名是 case_metadata
    db.commit()
    db.refresh(c)
    return c


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    c = _get_case_or_404(db, case_id)
    db.delete(c)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# 参考标准（纵向预测数据层）
# ---------------------------------------------------------------------------


@router.get("/reference-ranges", response_model=list[ReferenceRangeOut])
def list_reference_ranges(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    return db.query(ReferenceRange).order_by(ReferenceRange.indicator_name).all()


@router.get("/documents")
def list_operator_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """列出 access_scope 为 operator/both 的文档，供参考标准同步界面选择。

    不能复用 admin 文档接口——ai_operator 角色无权访问 admin API
    （admin.py 的文档接口依赖 require_admin）。

    sync_ready 表示该文档是否具备可同步的前置条件（status=indexed 且有 current chunks）；
    前端据此禁用不可同步的选项，避免选了 pending/failed 文档后走 422 失败路径。
    """
    docs = (
        db.query(Document)
        .filter(Document.access_scope.in_(("operator", "both")))
        .order_by(Document.created_at.desc())
        .all()
    )
    ready_doc_ids = {
        d.id
        for d in docs
        if d.status == "indexed"
        and db.query(Chunk.id)
        .filter(
            Chunk.document_id == d.id,
            Chunk.generation == d.active_generation,
            Chunk.is_current.is_(True),
        )
        .first()
        is not None
    }
    return [
        {
            "id": d.id,
            "title": d.title or d.filename,
            "filename": d.filename,
            "access_scope": d.access_scope,
            "status": d.status,
            "sync_ready": d.id in ready_doc_ids,
        }
        for d in docs
    ]
