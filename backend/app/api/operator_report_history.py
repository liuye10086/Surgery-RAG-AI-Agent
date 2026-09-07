from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.api.deps import require_ai_operator
from app.db.session import get_db
from app.db.models import User
from app.core.config import settings
from app.schemas.report_history import HistoryFilters, ReportHistoryPage
from app.services.report_history_query import read_history

router = APIRouter(prefix="/operator", tags=["operator"])


@router.get("/report-history", response_model=ReportHistoryPage)
def report_history(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=2048),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    params = dict(request.query_params)
    params.pop("limit", None)
    params.pop("cursor", None)
    try:
        filters = HistoryFilters.model_validate(params)
    except ValidationError:
        raise HTTPException(
            422,
            detail={"code": "history_filters_invalid", "message": "请核对报告筛选条件"},
        )
    key = settings.REPORT_HISTORY_CURSOR_SECRET.encode("utf-8")
    if len(key) < 32:
        raise HTTPException(
            503,
            detail={
                "code": "report_history_unavailable",
                "message": "历史报告服务暂未就绪",
            },
        )
    try:
        return read_history(
            db, current_user.id, filters, limit=limit, cursor=cursor, key=key
        )
    except ValueError:
        raise HTTPException(
            400,
            detail={
                "code": "history_cursor_invalid",
                "message": "分页标识无效，请刷新历史报告",
            },
        )
