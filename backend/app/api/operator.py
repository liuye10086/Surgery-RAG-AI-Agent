"""AI 操作者纵向预测报告、病例和标准数据 API 路由。"""

import logging
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_ai_operator
from app.db.models import (
    AIReport,
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
from app.schemas.operator_case_status import OperatorCaseStatus, OperatorCaseStatusChangeRequest
from app.schemas.operator_indicator_catalog import OperatorIndicatorCatalogOut
from app.services.pdf_generator import generate_pdf
from app.services.longitudinal_case_service import (
    ArchivedCaseError,
    CaseNotFoundError,
    get_operator_case,
    list_operator_cases,
    build_input_snapshot,
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
from app.services.longitudinal_report_generator import generate_longitudinal_report
from app.services.report_integrity import (
    compute_input_snapshot_sha256,
    verify_report_integrity,
)
from app.services.longitudinal_model_registry import load_active_model_registry
from app.services.longitudinal_evidence import (
    build_reference_range_sources,
    mark_synthetic_source,
    select_similar_longitudinal_cases,
)
from app.services.disease_catalog import (
    DISEASE_CAPABILITIES,
    DiseaseCapabilityMissingError,
    DiseaseCatalogError,
    DiseaseDisabledError,
    DiseaseNotFoundError,
    require_enabled_case_disease,
    require_disease_capability,
)
from app.services.indicator_validation import IndicatorValidationError
from app.services.operator_indicator_catalog import (
    IndicatorCatalogUnavailableError,
    load_operator_indicator_catalog,
)
from app.services.operator_case_readiness import evaluate_operator_case_readiness

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operator", tags=["operator"])


def _verify_report_owner(report: AIReport, current_user: User) -> None:
    """校验报告归属权。admin 也只能查看/操作自己创建的报告。"""
    if report.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="报告不存在",
        )


def _safe_report_title(report: AIReport) -> str:
    anonymous_code = (
        getattr(report, "anonymous_case_code", None)
        or getattr(getattr(report, "operator_case", None), "anonymous_case_code", None)
        or (getattr(report, "input_snapshot", None) or {}).get("anonymous_case_code")
    )
    return f"{anonymous_code}纵向进展预测报告" if anonymous_code else f"报告-{report.id}"


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
):
    try:
        case = get_operator_case(db, current_user.id, case_id)
    except (CaseNotFoundError, DiseaseCatalogError) as exc:
        raise _longitudinal_error(exc) from exc
    try:
        db.refresh(case, with_for_update=True)
    except (TypeError, AttributeError):
        pass
    readiness = evaluate_operator_case_readiness(case)
    if not readiness.ready:
        blocker = readiness.blockers[0] if readiness.blockers else None
        code = blocker.code if blocker else "report_not_ready"
        message = blocker.message if blocker else "病例尚未满足报告生成条件"
        service_blocked = any(
            item.code in {"model_unavailable", "indicator_catalog_unavailable"}
            for item in readiness.blockers
        )
        raise _operator_http_error(
            503 if service_blocked else 409,
            code,
            message,
        )
    try:
        disease = require_enabled_case_disease(case)
        adapter = DISEASE_CAPABILITIES[disease.code].adapter
    except DiseaseCatalogError as exc:
        raise _disease_http_error(exc) from exc
    options = (request or LongitudinalReportRequest()).model_options
    try:
        snapshot = build_input_snapshot(case, case.visits, options)
    except (
        OperatorCaseValidationError,
        IndicatorValidationError,
        IndicatorCatalogUnavailableError,
    ) as exc:
        raise _longitudinal_error(exc) from exc
    visits = snapshot["visits"]
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
    snapshot_hash = compute_input_snapshot_sha256(snapshot)
    snapshot["input_snapshot_sha256"] = snapshot_hash
    batch_id = str(uuid.uuid4())
    anonymous_code = getattr(case, "anonymous_case_code", None) or "旧病例未设置匿名编号"
    report = AIReport(user_id=current_user.id, operator_case_id=case.id, disease_id=case.disease_id, query=anonymous_code, title=f"{anonymous_code}纵向进展预测报告", indicators=[], analysis_type="longitudinal_predictive", status="generating", input_snapshot=snapshot)
    report.input_snapshot_sha256 = snapshot_hash
    report.generation_batch_id = batch_id
    db.add(report)
    db.commit()
    db.refresh(report)
    try:
        model_registry = load_active_model_registry(adapter.dataset)
    except Exception:
        report.status = "failed"
        report.error_message = "longitudinal_prediction_failed"
        report.error_stage = "model_loading"
        db.commit()
        raise _operator_http_error(
            503,
            "model_unavailable",
            "模型暂时不可用，请稍后重试",
        )
    return StreamingResponse(generate_longitudinal_report(db, report.id, snapshot, snapshot["visits"], adapter, model_registry=model_registry, sources=sources), media_type="text/event-stream")


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
    def _summary(report: AIReport) -> ReportListItem:
        snapshot = report.input_snapshot if isinstance(report.input_snapshot, dict) else {}
        prediction = report.prediction_result if isinstance(report.prediction_result, dict) else {}
        disease_name = snapshot.get("disease") if isinstance(snapshot.get("disease"), str) else None
        baseline_stage = snapshot.get("baseline_stage") if isinstance(snapshot.get("baseline_stage"), str) else None
        visits = snapshot.get("visits") if isinstance(snapshot.get("visits"), list) else []
        release_set = prediction.get("release_set") if isinstance(prediction.get("release_set"), dict) else {}
        version = release_set.get("release_set_id") or release_set.get("data_release_id")
        error_stage = getattr(report, "error_stage", None)
        if error_stage is None:
            if report.status == "generating":
                error_stage = "generating"
            elif report.status == "failed":
                error_stage = "failed"
            elif report.status == "cancelled":
                error_stage = "cancelled"
        return ReportListItem(
            id=report.id,
            user_id=report.user_id,
            title=_safe_report_title(report),
            query=_safe_report_title(report),
            department_ids=report.department_ids or [],
            status=report.status,
            error_message=report.error_message,
            download_count=report.download_count or 0,
            analysis_type=report.analysis_type,
            disease_id=report.disease_id,
            operator_case_id=report.operator_case_id,
            anonymous_case_code=getattr(report, "anonymous_case_code", None),
            indicators=report.indicators or [],
            disease_name=disease_name,
            baseline_stage=baseline_stage,
            visit_count=len(visits) if visits else None,
            model_version_summary=str(version) if version else None,
            error_stage=error_stage,
            input_snapshot_sha256=getattr(report, "input_snapshot_sha256", None),
            generation_batch_id=getattr(report, "generation_batch_id", None),
            generation_fingerprint=getattr(report, "generation_fingerprint", None),
            created_at=report.created_at,
            updated_at=report.updated_at,
        )

    return ReportListOut(reports=[_summary(r) for r in reports], total=total)


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
    result = ReportOut.model_validate(report)
    verification = verify_report_integrity(
        report.input_snapshot,
        getattr(report, "input_snapshot_sha256", None),
        getattr(report, "generation_fingerprint", None),
        report.prediction_result,
        report.content,
    )
    result.integrity_status = verification.status
    result.integrity_reason_code = verification.reason_code
    result.title = _safe_report_title(report)
    result.query = _safe_report_title(report)
    return result


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

    anonymous_code = (
        getattr(report, "anonymous_case_code", None)
        or getattr(getattr(report, "operator_case", None), "anonymous_case_code", None)
        or (getattr(report, "input_snapshot", None) or {}).get("anonymous_case_code")
    )
    # 新报告使用匿名病例编号；历史报告没有编号时只使用固定报告编号，
    # 避免把旧 title/query 中可能存在的身份信息带入下载文件名或 PDF 元数据。
    safe_title = _safe_report_title(report)
    # 历史报告的正文与既有 PDF 内容保持只读兼容；文件名单独使用安全标题。
    pdf_title = safe_title

    try:
        pdf_bytes = generate_pdf(report.content, pdf_title, report.prediction_result)
    except RuntimeError:
        logger.warning("PDF generation failed for report_id=%s", report_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF 生成暂时失败，请稍后重试",
        )

    # 更新下载计数
    report.download_count = (report.download_count or 0) + 1
    db.commit()

    # 构建安全 Content-Disposition（RFC 5987：ASCII fallback + UTF-8 编码文件名）
    safe_filename = f"report-{report_id}.pdf"
    encoded_title = urllib.parse.quote(f"{safe_title}.pdf", safe="")
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
