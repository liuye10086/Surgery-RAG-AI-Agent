import asyncio
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models import Message, Session as ChatSession, User
from app.db.session import get_db
from app.rag.adapters import AuditCallbackHandler, SurgeryChatMessageHistory
from app.rag.pipeline import SurgeryRetriever
from app.schemas.chat import (
    AskRequest,
    MessageOut,
    SessionCreate,
    SessionDetail,
    SessionOut,
)
from app.services.audit import log_chat
from app.services.content_filter import detect_dangerous_symptoms, filter_input
from app.services.llm_client import build_full_chain

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


def persist_user_message(
    db: Session,
    session_id: int,
    content: str,
    client_request_id: str | None,
) -> Message:
    """在输入通过安全检查后保存用户消息，并保证客户端重试幂等。"""
    if client_request_id:
        existing = (
            db.query(Message)
            .filter(
                Message.session_id == session_id,
                Message.client_request_id == client_request_id,
                Message.role == "user",
            )
            .first()
        )
        if existing:
            if existing.content != content:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="请求标识与已有内容冲突",
                )
            return existing

    message = Message(
        session_id=session_id,
        role="user",
        content=content,
        client_request_id=client_request_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

# ---------------------------------------------------------------------------
# 标题生成（独立 LLM 实例，非流式，低温度）
# ---------------------------------------------------------------------------

_title_llm = ChatOpenAI(
    model=settings.DEEPSEEK_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=False,
    temperature=0.1,
    max_tokens=20,
    request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
)

_title_prompt = ChatPromptTemplate.from_messages([
    ("system", "你是标题生成助手。将用户的问题总结为不超过12个字的简短标题。只输出标题，不要引号、标点或其他内容。"),
    ("human", "{question}"),
])

_title_chain = _title_prompt | _title_llm | StrOutputParser()


async def _generate_title(question: str) -> str:
    """用 LLM 自动总结用户首条问题为会话标题。"""
    try:
        title = await _title_chain.ainvoke({"question": question})
        return title.strip()[:12]
    except Exception:
        logger.exception("Failed to generate title, falling back to truncation")
        return question[:12]


def _update_session_title(db: Session, session_id: int, title: str) -> None:
    """更新会话标题。"""
    db.query(ChatSession).filter(ChatSession.id == session_id).update(
        {"title": title}
    )
    db.commit()


# ---------------------------------------------------------------------------
# 会话 CRUD（不变）
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=SessionOut)
def create_session(
    req: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = ChatSession(
        user_id=current_user.id,
        title=req.title or "新会话",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return sessions


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除会话及其所有消息（数据库级联）。"""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    db.delete(session)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# RAG 问答（核心改造：使用 RunnableWithMessageHistory + 完整 LCEL 链）
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/ask")
async def ask(
    session_id: int,
    req: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式 RAG 问答接口。

    使用 RunnableWithMessageHistory 自动管理消息历史，
    链内部完成查询改写、检索、知识充分性判断和回答生成。
    """
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    user_id = current_user.id
    is_first_message = session.title == "新会话" or not session.title

    # --- M5：输入安全过滤 + 危险症状检测 ---
    safety_flags: dict = {}

    # 输入长度检查
    if len(req.content) > settings.INPUT_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"输入过长，最多 {settings.INPUT_MAX_LENGTH} 字符",
        )

    # 越狱/注入检测
    input_result = filter_input(req.content)
    if input_result.blocked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=input_result.reason,
        )
    if input_result.flagged:
        safety_flags["input_flagged"] = True
        safety_flags["input_flag_reason"] = input_result.flag_reason

    user_message = None
    if not req.retry_message_id:
        user_message = persist_user_message(
            db,
            session_id,
            req.content,
            req.client_request_id,
        )

    # 危险症状检测
    danger_result = detect_dangerous_symptoms(req.content)
    if danger_result.level:
        safety_flags["danger_level"] = danger_result.level

    # 首条消息时提前生成标题
    generated_title: Optional[str] = None
    if is_first_message:
        generated_title = await _generate_title(req.content)

    async def event_stream():
        # 在 generator 内部持有 history 引用，异常处理时可用
        history: Optional[SurgeryChatMessageHistory] = None
        full_answer = ""
        sources: list = []
        rewritten: str = ""
        is_no_knowledge: bool = False
        output_filter_reasons: list[str] = []
        message_id = None
        audit_cb = None

        try:
            # 发送危险症状事件（不阻断，正常问答）
            if danger_result.level:
                yield f"event: danger\ndata: {json.dumps({'level': danger_result.level, 'advice': danger_result.advice})}\n\n"

            # 1. 创建消息历史（支持重试）
            history = SurgeryChatMessageHistory(
                session_id=session_id,
                db=db,
                retry_message_id=req.retry_message_id,
            )

            # 2. 创建检索器
            retriever = SurgeryRetriever(
                db=db, top_k=settings.RETRIEVER_FINAL_TOP_K
            )

            # 3. 构建完整链并挂载消息历史
            chain = build_full_chain(retriever)
            chain_with_history = RunnableWithMessageHistory(
                chain,
                lambda _: history,
                input_messages_key="input",
                history_messages_key="history",
            )

            # 4. 审计回调
            audit_cb = AuditCallbackHandler()

            # 5. 流式执行
            final_chunk = None
            stage_sent = False

            async for chunk in chain_with_history.astream(
                {"input": req.content},
                config={
                    "callbacks": [audit_cb],
                    "configurable": {"session_id": str(session_id)},
                },
            ):
                final_chunk = chunk

                # 非内容 chunk 跳过（如工具调用等，当前链不会产生）
                if not hasattr(chunk, "content") or not chunk.content:
                    continue

                # 首个 delta 前发送 stage 事件
                if not stage_sent:
                    stage_sent = True
                    yield f"event: stage\ndata: {json.dumps({'stage': 'generating'})}\n\n"

                text = chunk.content
                full_answer += text
                yield f"event: delta\ndata: {json.dumps({'content': text})}\n\n"

            # 6. 从最终 chunk 提取 sources 和元数据
            if final_chunk and hasattr(final_chunk, "additional_kwargs"):
                sources = final_chunk.additional_kwargs.get("sources", [])
                rewritten = final_chunk.additional_kwargs.get("rewritten", "")
                is_no_knowledge = final_chunk.additional_kwargs.get("is_no_knowledge", False)
                output_filter_reasons = final_chunk.additional_kwargs.get(
                    "output_filter_reasons", []
                )

            # 7. 消息 ID
            if req.retry_message_id:
                message_id = req.retry_message_id
            else:
                saved_msg = (
                    db.query(Message)
                    .filter(
                        Message.session_id == session_id,
                        Message.role == "assistant",
                    )
                    .order_by(Message.created_at.desc())
                    .first()
                )
                message_id = saved_msg.id if saved_msg else None

        except (asyncio.CancelledError, GeneratorExit):
            logger.warning("Stream cancelled (client disconnect) for session %d", session_id)
            try:
                db.rollback()
            except Exception:
                pass
            # 客户端已断开，无需尝试发送错误事件
            return
        except Exception as e:
            logger.exception("Error in ask stream")
            try:
                db.rollback()
            except Exception:
                pass

            # 保存错误消息
            error_message_id: Optional[int] = None
            try:
                error_detail = f"生成失败：{str(e)}"
                if history is not None and req.retry_message_id:
                    # 重试场景：更新已有错误消息
                    existing = (
                        db.query(Message)
                        .filter(
                            Message.id == req.retry_message_id,
                            Message.session_id == session_id,
                        )
                        .first()
                    )
                    if existing:
                        existing.content = error_detail
                        existing.sources = []
                        existing.is_error = True
                        db.commit()
                        error_message_id = existing.id
                    else:
                        msg = Message(
                            session_id=session_id,
                            role="assistant",
                            content=error_detail,
                            sources=[],
                            is_error=True,
                        )
                        db.add(msg)
                        db.commit()
                        db.refresh(msg)
                        error_message_id = msg.id
                else:
                    msg = Message(
                        session_id=session_id,
                        role="assistant",
                        content=error_detail,
                        sources=[],
                        is_error=True,
                    )
                    db.add(msg)
                    db.commit()
                    db.refresh(msg)
                    error_message_id = msg.id

                if is_first_message and generated_title:
                    _update_session_title(db, session_id, generated_title)
            except Exception:
                logger.exception("Failed to persist error message")

            yield f"event: error\ndata: {json.dumps({'detail': str(e), 'title': generated_title, 'message_id': error_message_id})}\n\n"
            return

        if output_filter_reasons:
            safety_flags["output_flagged"] = True
            safety_flags["output_filter_reasons"] = output_filter_reasons

        # --- 8. 审计日志（非关键路径：失败不影响已成功的响应流）---
        try:
            log_chat(
                db=db,
                user_id=user_id,
                session_id=session_id,
                request_body={
                    "question": req.content,
                    "rewritten": rewritten,
                },
                retrieved_chunk_ids=audit_cb.retrieved_chunk_ids,
                response_text=full_answer,
                latency_ms=audit_cb.latency_ms,
                model=settings.DEEPSEEK_MODEL,
                safety_flags=safety_flags,
            )
        except Exception:
            logger.exception("Audit log failed, response already sent to client")

        # --- 9. 首条消息更新标题（非关键路径：失败不影响已成功的响应流）---
        try:
            if is_first_message and generated_title:
                _update_session_title(db, session_id, generated_title)
        except Exception:
            logger.exception("Update session title failed, response already sent to client")

        yield f"event: sources\ndata: {json.dumps({'sources': sources})}\n\n"
        status = 'no_knowledge' if is_no_knowledge else 'done'
        yield f"event: done\ndata: {json.dumps({'status': status, 'message_id': message_id, 'user_message_id': user_message.id if user_message else None, 'title': generated_title, 'is_no_knowledge': is_no_knowledge})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
