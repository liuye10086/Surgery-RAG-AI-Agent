"""用户数据导出与账户删除（个保法合规）。"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import AuditLog, Session as ChatSession, User
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["user"])


class DeleteAccountRequest(BaseModel):
    password: str


# ---------------------------------------------------------------------------
# GET /user/export
# ---------------------------------------------------------------------------

@router.get("/export")
def export_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出用户全部个人数据（个保法第 45 条）。"""
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at)
        .all()
    )

    export_data_dict = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "real_name": user.real_name,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "sessions": [],
    }

    for session in sessions:
        session_data = {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "sources": msg.sources,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                for msg in sorted(session.messages, key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc))
            ],
        }
        export_data_dict["sessions"].append(session_data)

    # 审计日志
    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at)
        .all()
    )
    export_data_dict["audit_logs"] = [
        {
            "session_id": log.session_id,
            "request_body": log.request_body,
            "retrieved_chunk_ids": log.retrieved_chunk_ids,
            "latency_ms": log.latency_ms,
            "model": log.model,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in audit_logs
    ]

    json_str = json.dumps(export_data_dict, ensure_ascii=False, indent=2)
    filename = f"data_export_{user.username}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# DELETE /user/account
# ---------------------------------------------------------------------------

@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    req: DeleteAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除账户及全部关联数据（个保法第 47 条）。

    需要用户提供当前密码验证身份。
    删除策略：
    - users: 硬删除
    - sessions/messages: 级联删除（FK CASCADE）
    - audit_logs: 保留匿名运行统计，清除问题、回答和检索明细
    - documents: 不受影响（知识库属系统资产）
    """
    from app.core.security import verify_password

    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码错误",
        )

    logger.warning("Deleting account for user %s (id=%d)", user.username, user.id)

    # 审计日志可用于统计稳定性，但销户后不得继续保存可识别的病情文本。
    audit_logs = db.query(AuditLog).filter(AuditLog.user_id == user.id).all()
    for log in audit_logs:
        log.request_body = None
        log.response_text = None
        log.retrieved_chunk_ids = []
        log.user_id = None
        log.session_id = None

    db.delete(user)
    db.commit()

    return None
