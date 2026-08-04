"""AI 操作者报告 API 路由。

提供 5 个端点：
  POST   /operator/reports          — 创建并流式生成报告（SSE）
  GET    /operator/reports          — 列出当前用户报告（分页）
  GET    /operator/reports/{id}     — 获取单个报告详情
  DELETE /operator/reports/{id}     — 删除报告
  GET    /operator/reports/{id}/download — 下载 PDF
"""

import asyncio
import json
import logging
import time as _time
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_ai_operator
from app.core.config import settings
from app.db.models import (
    AIReport,
    AuditLog,
    CaseRecord,
    Chunk,
    Department,
    Disease,
    Document,
    ReferenceRange,
    User,
)
from app.db.session import get_db
from app.schemas.operator import (
    ReportGenerateRequest,
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
    ReferenceRangeSyncIn,
)
from app.services.pdf_generator import generate_pdf
from app.services.reference_standard import sync_reference_ranges
from app.services.report_generator import generate_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operator", tags=["operator"])


def _verify_report_owner(report: AIReport, current_user: User) -> None:
    """校验报告归属权。admin 也只能查看/操作自己创建的报告。"""
    if report.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="报告不存在",
        )


# ---------------------------------------------------------------------------
# POST /operator/reports — 创建并流式生成报告
# ---------------------------------------------------------------------------


@router.post("/reports")
async def create_and_generate_report(
    request: ReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """创建报告记录并流式生成，SSE 响应。

    客户端应使用 fetch + ReadableStream（非 EventSource）读取，
    因为此接口为 POST 且需 JSON body。
    可通过 AbortController.abort() 取消请求以触发 cancelled 标记。
    """
    start_time = _time.monotonic()

    # 1. 前置校验：analysis_backend
    if request.analysis_backend not in ("llm",):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"未知的 analysis_backend: {request.analysis_backend}",
        )

    # 2. 前置校验：department_ids（避免创建记录后才发现无效科室）
    from app.services.report_generator import _validate_department_ids
    try:
        _validate_department_ids(db, request.department_ids)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # 3. 创建 ai_reports 记录（status=generating）
    report = AIReport(
        user_id=current_user.id,
        query=request.query,
        department_ids=request.department_ids or [],
        status="generating",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    report_id = report.id
    current_user_id = current_user.id  # 捕获 int，避免 ORM 对象在生成器内 expire 后 detached

    async def _stream_and_cleanup():
        """流式生成 + finally 块处理取消/异常的状态标记。"""
        try:
            async for sse_event in generate_report(
                db=db,
                user_id=current_user_id,
                report_id=report_id,
                query=request.query,
                department_ids=request.department_ids,
                analysis_backend=request.analysis_backend,
            ):
                yield sse_event
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断连 → 标记 cancelled（仅 generating → cancelled）
            logger.warning(
                "Report generation cancelled by client for report_id=%s", report_id
            )
            try:
                r = db.query(AIReport).filter(AIReport.id == report_id).first()
                if r and r.status == "generating":
                    r.status = "cancelled"
                    r.error_message = "用户取消生成"
                    db.commit()
            except Exception:
                logger.exception("Failed to mark report %s as cancelled", report_id)
            # 客户端已断开，不需要继续 yield
            return
        finally:
            # 审计日志（非关键路径）
            elapsed_ms = int((_time.monotonic() - start_time) * 1000)
            try:
                final_report = (
                    db.query(AIReport).filter(AIReport.id == report_id).first()
                )
                retrieved_chunk_ids = []
                if final_report and final_report.retrieval_meta:
                    retrieved_chunk_ids = (
                        final_report.retrieval_meta.get("retrieved_chunk_ids", [])
                    )
                audit = AuditLog(
                    user_id=current_user_id,
                    session_id=None,
                    request_body={
                        "feature": "operator_report",
                        "action": "generate",
                        "report_id": report_id,
                        "query": request.query,
                        "department_ids": request.department_ids,
                    },
                    model=settings.DEEPSEEK_MODEL,
                    latency_ms=elapsed_ms,
                    retrieved_chunk_ids=retrieved_chunk_ids,
                    safety_flags={},
                )
                db.add(audit)
                db.commit()
            except Exception:
                logger.exception("Audit log failed for report %s", report_id)

    return StreamingResponse(
        _stream_and_cleanup(),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# GET /operator/reports — 列出报告
# ---------------------------------------------------------------------------


@router.get("/reports", response_model=ReportListOut)
def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """列出当前用户创建的报告，按创建时间倒序。"""
    total = (
        db.query(AIReport)
        .filter(AIReport.user_id == current_user.id)
        .count()
    )
    reports = (
        db.query(AIReport)
        .filter(AIReport.user_id == current_user.id)
        .order_by(AIReport.created_at.desc())
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
# 疾病 CRUD（AI 操作者预测分析）
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
    d = db.query(Disease).filter(Disease.id == disease_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="疾病不存在")
    if db.query(CaseRecord).filter(CaseRecord.disease_id == disease_id).count():
        raise HTTPException(status_code=409, detail="该疾病下存在病例，请先删除病例")
    db.delete(d)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# 病例 CRUD（AI 操作者预测分析）
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
# 参考标准（AI 操作者预测分析）
# ---------------------------------------------------------------------------


@router.post("/reference-ranges/sync")
def sync_reference_ranges_endpoint(
    payload: ReferenceRangeSyncIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        result = sync_reference_ranges(db, payload.document_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


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
