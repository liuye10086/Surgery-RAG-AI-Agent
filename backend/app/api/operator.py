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
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_ai_operator
from app.core.config import settings
from app.db.models import AIReport, AuditLog, Department, User
from app.db.session import get_db
from app.schemas.operator import (
    ReportGenerateRequest,
    ReportListOut,
    ReportListItem,
    ReportOut,
)
from app.services.pdf_generator import generate_pdf
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
