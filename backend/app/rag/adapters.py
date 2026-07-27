import logging
import time
from typing import Any, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    messages_from_dict,
    message_to_dict,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Message
from app.services.embedder import embed_texts

logger = logging.getLogger(__name__)


class SurgeryEmbeddings(Embeddings):
    """把项目已有的 bge-m3 embedder 包装成 LangChain Embeddings 接口。"""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        return embed_texts(texts)

    def embed_query(self, text: str) -> List[float]:
        embeddings = embed_texts([text])
        if not embeddings:
            return []
        return embeddings[0]


class SurgeryChatMessageHistory(BaseChatMessageHistory):
    """把现有 `messages` 表包装成 LangChain 的 ChatMessageHistory。

    - 读取时优先从 lc_message JSONB 反序列化，兼容旧 role/content 降级。
    - 写入时生成 lc_message JSONB 并同步保留冗余列，前端无需改动。
    - 支持 retry_message_id：重试时更新已有消息而非新增。
    """

    def __init__(
        self,
        session_id: int,
        db: Session,
        retry_message_id: Optional[int] = None,
    ):
        self.session_id = session_id
        self.db = db
        self.retry_message_id = retry_message_id

    @property
    def messages(self) -> List[BaseMessage]:
        rows = (
            self.db.query(Message)
            .filter(Message.session_id == self.session_id)
            .filter(Message.is_error == False)
            .order_by(Message.created_at.desc())
            .limit(settings.CHAT_MEMORY_ROUNDS * 2)  # x2: each round = user + assistant (2 messages)
            .all()
        )
        # 查询取最新 N 条（DESC），反转回时间正序供 LLM 使用
        rows.reverse()
        result: List[BaseMessage] = []
        for row in rows:
            # 优先从 LangChain 标准 JSON 反序列化
            if row.lc_message:
                try:
                    deserialized = messages_from_dict([row.lc_message])
                    result.extend(deserialized)
                    continue
                except Exception:
                    logger.warning(
                        "Failed to deserialize lc_message for message %d, falling back", row.id
                    )

            # 降级：从 role/content 重建（兼容旧数据）
            if row.role == "user":
                result.append(HumanMessage(content=row.content))
            elif row.role == "assistant":
                result.append(AIMessage(content=row.content))
        return result

    def add_message(self, message: BaseMessage) -> None:
        # 用户消息由前端通过 POST /messages 手动保存，
        # 此处仅处理 assistant 消息，避免重复写入。
        #
        # 注意：此方法使用 flush() 而非 commit()，将提交职责交给上层调用方
        # （如 chat.py 中的 log_chat()），以保证 add_message 与后续审计日志写入
        # 处于同一事务中，支持原子性回滚。
        if isinstance(message, HumanMessage):
            return

        if isinstance(message, AIMessage):
            role = "assistant"
        else:
            # 系统消息等不存入业务消息表
            return

        lc_message = message_to_dict(message)
        sources = message.additional_kwargs.get("sources", [])
        is_error = message.additional_kwargs.get("is_error", False)
        is_no_knowledge = message.additional_kwargs.get("is_no_knowledge", False)

        # 流式场景下最终 chunk 的 content 为空，完整文本在 full_content 中
        content = message.content or message.additional_kwargs.get("full_content", "")

        # 重试场景：更新已有 assistant 消息，不新增
        if self.retry_message_id:
            existing = (
                self.db.query(Message)
                .filter(
                    Message.id == self.retry_message_id,
                    Message.session_id == self.session_id,
                )
                .first()
            )
            if existing:
                existing.lc_message = lc_message
                existing.content = content
                existing.role = role
                existing.sources = sources
                existing.is_error = is_error
                existing.is_no_knowledge = is_no_knowledge
                self.db.flush()
                return

            # retry_message_id 存在但不在当前会话中：检查是否属于其他会话
            cross_session = (
                self.db.query(Message)
                .filter(Message.id == self.retry_message_id)
                .first()
            )
            if cross_session:
                logger.error(
                    "retry_message_id=%d belongs to session %d, not current session %d",
                    self.retry_message_id,
                    cross_session.session_id,
                    self.session_id,
                )
                raise ValueError(
                    f"retry_message_id {self.retry_message_id} does not belong to session {self.session_id}"
                )
            else:
                logger.warning(
                    "retry_message_id=%d not found in any session, creating new message",
                    self.retry_message_id,
                )

        self.db.add(
            Message(
                session_id=self.session_id,
                role=role,
                content=content,
                lc_message=lc_message,
                sources=sources,
                is_error=is_error,
                is_no_knowledge=is_no_knowledge,
            )
        )
        self.db.flush()

    def add_user_message(self, message: str) -> None:
        """直接持久化用户消息到数据库。

        不调用 add_message()，因为 add_message() 会跳过 HumanMessage。
        前端仍通过 POST /messages 作为主路径保存用户消息，此方法作为补充路径。
        """
        lc_message = message_to_dict(HumanMessage(content=message))
        self.db.add(
            Message(
                session_id=self.session_id,
                role="user",
                content=message,
                lc_message=lc_message,
            )
        )
        self.db.commit()

    def add_ai_message(self, message: str) -> None:
        self.add_message(AIMessage(content=message))

    def clear(self) -> None:
        self.db.query(Message).filter(Message.session_id == self.session_id).delete()
        self.db.commit()


class AuditCallbackHandler(BaseCallbackHandler):
    """在 LangChain 链执行过程中捕获审计所需信息。

    使用 _depth 追踪嵌套链层级，确保只在最外层链上重置/计算，
    避免 LCEL 管道中 RunnableLambda 触发嵌套回调时清空数据。
    """

    def __init__(self) -> None:
        super().__init__()
        self.start_ms: float | None = None
        self.retrieved_chunk_ids: List[int] = []
        self.response_text: str = ""
        self.latency_ms: int = 0
        self._depth: int = 0

    def on_chain_start(
        self, serialized: dict[str, Any] | None, inputs: dict[str, Any], **kwargs: Any
    ) -> None:
        self._depth += 1
        if self._depth == 1:
            self.start_ms = time.time() * 1000
            self.response_text = ""
            self.retrieved_chunk_ids = []

    def on_retriever_end(
        self, documents: List[Document], **kwargs: Any
    ) -> None:
        self.retrieved_chunk_ids = [
            int(doc.metadata.get("chunk_id"))
            for doc in documents
            if doc.metadata.get("chunk_id") is not None
        ]

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self.response_text += token

    def on_chain_end(self, outputs: Any, **kwargs: Any) -> None:
        if self._depth == 1 and self.start_ms is not None:
            self.latency_ms = int(time.time() * 1000 - self.start_ms)
        self._depth = max(0, self._depth - 1)
