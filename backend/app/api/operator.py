"""AI 操作者纵向预测报告、病例和标准数据 API 路由。"""

import urllib.parse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import oauth2_scheme, require_ai_operator
from app.db.models import (
    Chunk,
    Disease,
    Document,
    ReferenceRange,
    User,
)
from app.db.session import get_db
from app.schemas.operator import (
    ReportListOut,
)
from app.schemas.report_read_models import ReportReadDetail
from app.schemas.prediction import DiseaseOut, ReferenceRangeOut
from app.schemas.longitudinal_case import (
    OperatorCaseCreate,
    OperatorCaseListOut,
    OperatorCaseOut,
)
from app.schemas.longitudinal_report import LongitudinalReportRequest
from app.schemas.operator_case_workspace import (
    OperatorCaseReportReadiness,
    OperatorCaseSave,
)
from app.schemas.operator_case_status import (
    OperatorCaseStatus,
    OperatorCaseStatusChangeRequest,
)
from app.schemas.operator_indicator_catalog import OperatorIndicatorCatalogOut
from app.services.longitudinal_case_service import (
    ArchivedCaseError,
    CaseNotFoundError,
    get_operator_case,
    list_operator_cases,
)
from app.services.operator_case_commands import (
    OperatorCaseCommandError,
    create_operator_case_command,
    delete_operator_case_command,
    save_operator_case_command,
)
from app.services.operator_case_idempotency import (
    IdempotencyConflictError,
    IdempotencyKeyError,
)
from app.services.operator_case_validation import OperatorCaseValidationError
from app.services.operator_case_status_service import (
    CaseStatusConflictError,
    CaseStatusNotFoundError,
    CaseStatusReasonError,
    OperatorCaseStatusError,
    change_operator_case_status,
)
from app.services.report_read_service import read_owned_report
from app.services.disease_catalog import (
    DISEASE_CAPABILITIES,
    DiseaseCapabilityMissingError,
    DiseaseCatalogError,
    DiseaseDisabledError,
    DiseaseNotFoundError,
    require_disease_capability,
)
from app.services.indicator_validation import IndicatorValidationError
from app.services.operator_indicator_catalog import (
    IndicatorCatalogUnavailableError,
    load_operator_indicator_catalog,
)
from app.services.operator_case_readiness import evaluate_operator_case_readiness

router = APIRouter(prefix="/operator", tags=["operator"])


# ---------------------------------------------------------------------------
# /operator/longitudinal-cases — 操作者自有纵向病例与访视
# ---------------------------------------------------------------------------


def _longitudinal_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IndicatorCatalogUnavailableError):
        return _operator_http_error(
            503,
            "indicator_catalog_unavailable",
            "指标目录暂时不可用，请稍后重试",
        )
    if isinstance(exc, (CaseNotFoundError, CaseStatusNotFoundError)):
        # Do not reveal whether another operator owns the resource.
        return _operator_http_error(404, "case_not_found", "病例不存在")
    if isinstance(exc, IdempotencyKeyError):
        return _operator_http_error(400, exc.code, exc.message)
    if isinstance(exc, IdempotencyConflictError):
        return _operator_http_error(409, exc.code, exc.message)
    if isinstance(exc, DiseaseCatalogError):
        return _disease_http_error(exc)
    if isinstance(exc, (ArchivedCaseError, CaseStatusConflictError)):
        return _operator_http_error(409, "case_read_only", str(exc))
    if isinstance(exc, CaseStatusReasonError):
        return _operator_http_error(422, "status_reason_invalid", str(exc))
    if isinstance(exc, OperatorCaseStatusError):
        return _operator_http_error(422, "case_status_invalid", str(exc))
    if isinstance(exc, OperatorCaseCommandError):
        status_code = 409 if exc.code == "case_write_conflict" else 422
        return _operator_http_error(
            status_code,
            exc.code,
            exc.message,
            field=exc.field,
        )
    if isinstance(exc, OperatorCaseValidationError):
        return _operator_http_error(
            422,
            exc.code,
            exc.message,
            field=exc.field,
            issues=exc.issues,
        )
    if isinstance(exc, IndicatorValidationError):
        return _operator_http_error(422, "indicators_invalid", str(exc))
    return _operator_http_error(422, "operator_case_invalid", "病例数据无效")


def _operator_http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    field: str | None = None,
    issues: list[dict[str, str]] | None = None,
) -> HTTPException:
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    if issues:
        detail["issues"] = [
            {
                key: value
                for key, value in issue.items()
                if key in {"code", "message", "field"} and isinstance(value, str)
            }
            for issue in issues
        ]
    return HTTPException(status_code=status_code, detail=detail)


def _disease_http_error(exc: DiseaseCatalogError) -> HTTPException:
    if isinstance(exc, DiseaseDisabledError):
        return _operator_http_error(
            409,
            "disease_disabled",
            "该疾病已停用，病例当前只读",
        )
    if isinstance(exc, DiseaseCapabilityMissingError):
        return _operator_http_error(
            422,
            "disease_capability_missing",
            "该疾病未开放 AI 操作者使用",
        )
    if isinstance(exc, DiseaseNotFoundError):
        return _operator_http_error(422, "disease_not_found", "疾病不存在")
    return _operator_http_error(422, "disease_invalid", "疾病配置无效")


@router.post("/longitudinal-cases", response_model=OperatorCaseOut, status_code=201)
def create_longitudinal_case(
    payload: OperatorCaseCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return create_operator_case_command(
            db,
            current_user.id,
            payload,
            idempotency_key,
        )
    except (
        DiseaseCatalogError,
        CaseNotFoundError,
        IdempotencyKeyError,
        IdempotencyConflictError,
        OperatorCaseCommandError,
        OperatorCaseValidationError,
        IndicatorValidationError,
        IndicatorCatalogUnavailableError,
    ) as exc:
        raise _longitudinal_error(exc) from exc


@router.get("/longitudinal-cases", response_model=OperatorCaseListOut)
def list_longitudinal_cases(
    q: str | None = Query(None, min_length=1, max_length=50),
    disease_id: int | None = Query(None),
    status_filter: OperatorCaseStatus | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    cases, total = list_operator_cases(
        db,
        current_user.id,
        q=q,
        disease_id=disease_id,
        status=status_filter.value if status_filter else None,
        skip=skip,
        limit=limit,
    )
    return OperatorCaseListOut(cases=cases, total=total, skip=skip, limit=limit)


@router.get("/longitudinal-cases/{case_id}", response_model=OperatorCaseOut)
def get_longitudinal_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return get_operator_case(db, current_user.id, case_id)
    except (CaseNotFoundError, DiseaseCatalogError, ArchivedCaseError) as exc:
        raise _longitudinal_error(exc) from exc


@router.put("/longitudinal-cases/{case_id}", response_model=OperatorCaseOut)
def update_longitudinal_case(
    case_id: int,
    payload: OperatorCaseSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return save_operator_case_command(db, current_user.id, case_id, payload)
    except (
        CaseNotFoundError,
        DiseaseCatalogError,
        ArchivedCaseError,
        OperatorCaseCommandError,
        OperatorCaseValidationError,
        IndicatorValidationError,
        IndicatorCatalogUnavailableError,
    ) as exc:
        raise _longitudinal_error(exc) from exc


@router.delete("/longitudinal-cases/{case_id}", status_code=204)
def delete_longitudinal_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        delete_operator_case_command(db, current_user.id, case_id)
    except (CaseNotFoundError, DiseaseCatalogError, ArchivedCaseError) as exc:
        raise _longitudinal_error(exc) from exc


@router.put(
    "/longitudinal-cases/{case_id}/status",
    response_model=OperatorCaseOut,
)
def update_longitudinal_case_status(
    case_id: int,
    payload: OperatorCaseStatusChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return change_operator_case_status(db, current_user.id, case_id, payload)
    except (
        CaseStatusNotFoundError,
        CaseStatusConflictError,
        CaseStatusReasonError,
        OperatorCaseStatusError,
        DiseaseCatalogError,
    ) as exc:
        raise _longitudinal_error(exc) from exc
    return None


@router.get(
    "/longitudinal-cases/{case_id}/report-readiness",
    response_model=OperatorCaseReportReadiness,
)
def get_longitudinal_report_readiness(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        case = get_operator_case(db, current_user.id, case_id)
    except (CaseNotFoundError, DiseaseCatalogError) as exc:
        raise _longitudinal_error(exc) from exc
    return evaluate_operator_case_readiness(case)


@router.post("/longitudinal-cases/{case_id}/reports")
async def create_longitudinal_report(
    case_id: int,
    request: LongitudinalReportRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
    idempotency_key: str | None = Header(default=None),
    token: str = Depends(oauth2_scheme),
):
    from app.api.operator_report_jobs import legacy_submit

    return legacy_submit(
        case_id,
        (request or LongitudinalReportRequest()).model_dump(),
        db,
        current_user,
        idempotency_key,
        token,
    )


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
    from app.services.report_history_query import read_offset_reports
    return read_offset_reports(db, current_user.id, skip=skip, limit=limit, analysis_type=analysis_type)



# ---------------------------------------------------------------------------
# GET /operator/reports/{id} — 报告详情
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}", response_model=ReportReadDetail)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """读取通过完整性校验及隐私投影的保存报告。"""
    return read_owned_report(db, current_user.id, report_id)


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
    from app.services.report_archive_cleanup import delete_owned_report
    from app.core.config import settings
    from fastapi.responses import JSONResponse, Response
    from app.services.report_generation_errors import ReportJobError
    from app.api.operator_report_jobs import http_error

    user_id = current_user.id
    db.rollback()
    try:
        result = delete_owned_report(db, user_id, report_id, settings.REPORT_ARCHIVE_ROOT)
    except ReportJobError as exc:
        raise http_error(exc) from exc
    if result.cleanup_state == 'pending':
        return JSONResponse(status_code=202,content={'deleted':True,'cleanup_state':'pending','message':'报告已删除，文件清理中'})
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /operator/reports/{id}/download — 下载 PDF
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}/download")
def download_report_pdf(
    report_id: int,
    range_header: str | None = Header(None, alias="Range"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """交付已归档且通过校验的原件；不在 HTTP 请求中渲染。"""
    from app.services.report_pdf_delivery import prepare_delivery, delivery_chunks
    from app.services.report_pdf_errors import PdfError
    from app.api.operator_report_archives import pdf_http_error
    from starlette.background import BackgroundTask

    try:
        delivery = prepare_delivery(db, current_user.id, report_id, range_requested=isinstance(range_header, str))
    except PdfError as error:
        raise pdf_http_error(error)
    disposition = f"attachment; filename=\"report-{report_id}.pdf\"; filename*=UTF-8''{urllib.parse.quote(delivery.filename, safe='')}"
    return StreamingResponse(delivery_chunks(delivery), media_type="application/pdf",
        headers={"Content-Disposition": disposition, "Content-Length": str(delivery.size_bytes),
                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "none"},
        background=BackgroundTask(delivery.file.close))


# ---------------------------------------------------------------------------
# 疾病 CRUD（纵向预测数据层）
# ---------------------------------------------------------------------------


@router.get("/diseases", response_model=list[DiseaseOut])
def list_diseases(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    supported_codes = tuple(DISEASE_CAPABILITIES)
    return (
        db.query(Disease)
        .filter(
            Disease.operator_enabled.is_(True),
            Disease.code.in_(supported_codes),
        )
        .order_by(Disease.id)
        .all()
    )


@router.get(
    "/diseases/{disease_code}/indicators",
    response_model=OperatorIndicatorCatalogOut,
)
def get_operator_indicator_catalog(
    disease_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        disease = db.query(Disease).filter(Disease.code == disease_code).first()
        if disease is None:
            raise DiseaseNotFoundError("疾病不存在")
        if not disease.operator_enabled:
            raise DiseaseDisabledError("该疾病已停用")
        require_disease_capability(disease.code)
    except DiseaseCatalogError as exc:
        raise _disease_http_error(exc) from exc
    try:
        return load_operator_indicator_catalog(disease.code).to_schema()
    except IndicatorCatalogUnavailableError as exc:
        raise _operator_http_error(
            503,
            "indicator_catalog_unavailable",
            "指标目录暂时不可用，请稍后重试",
        ) from exc


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
