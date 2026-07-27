from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def log_chat(
    db: Session,
    user_id: int,
    session_id: int,
    request_body: Dict[str, Any],
    retrieved_chunk_ids: List[int],
    response_text: str,
    latency_ms: int,
    model: str,
    safety_flags: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user_id,
        session_id=session_id,
        request_body=request_body,
        retrieved_chunk_ids=retrieved_chunk_ids,
        response_text=response_text,
        latency_ms=latency_ms,
        model=model,
        safety_flags=safety_flags or {},
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
