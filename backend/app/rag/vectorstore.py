"""PGVector 封装层。

提供 LangChain PGVector 实例的获取和与业务表 chunks 联动的辅助函数。
PGVector 会在首次使用时自动创建 langchain_pg_collection 和 langchain_pg_embedding 表。
"""

import logging
from typing import List, Optional

from langchain_core.documents import Document
from langchain_postgres import PGVector
from sqlalchemy import create_engine, text as sa_text

from app.core.config import settings
from app.rag.adapters import SurgeryEmbeddings

logger = logging.getLogger(__name__)

_embeddings = SurgeryEmbeddings()
_store: Optional[PGVector] = None
_tables_ensured = False


def get_vectorstore() -> PGVector:
    """获取 PGVector 实例（单例）。

    首次调用时会触发 PGVector 自动创建 langchain_pg_collection
    和 langchain_pg_embedding 表。
    """
    global _store
    if _store is None:
        conn_str = settings.VECTOR_STORE_CONNECTION_STRING or settings.DATABASE_URL
        _store = PGVector(
            connection=conn_str,
            embeddings=_embeddings,
            collection_name=settings.VECTOR_COLLECTION_NAME,
        )
        logger.info(
            "PGVector initialized: collection=%s", settings.VECTOR_COLLECTION_NAME
        )
    return _store


def ensure_vectorstore_tables() -> None:
    """确保 PGVector 表存在并建立全文检索 GIN 索引。

    应在应用启动时调用一次。PGVector 构造函数已自动建表，
    此函数补建 langchain_pg_embedding.document 上的 pg_trgm GIN 索引。
    使用 pg_trgm 替代 tsvector 以支持中文等无空格分隔语言的全文检索。
    """
    global _tables_ensured
    if _tables_ensured:
        return

    # 触发 PGVector 建表
    get_vectorstore()

    # 在 PGVector 的 document 列上建 pg_trgm GIN 索引（支持中文）
    conn_str = settings.VECTOR_STORE_CONNECTION_STRING or settings.DATABASE_URL
    engine = create_engine(conn_str)
    try:
        with engine.connect() as conn:
            # 启用 pg_trgm 扩展
            conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            # 使用 gin_trgm_ops 替代 tsvector（支持中英文混合检索）
            conn.execute(
                sa_text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_langchain_embedding_document_trgm
                    ON langchain_pg_embedding
                    USING GIN (document gin_trgm_ops)
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_langchain_embedding_title_trgm
                    ON langchain_pg_embedding
                    USING GIN ((cmetadata->>'document_title') gin_trgm_ops)
                    """
                )
            )
            # 清理旧版 tsvector 索引（已迁移到 pg_trgm）
            conn.execute(
                sa_text(
                    "DROP INDEX IF EXISTS idx_langchain_embedding_document_fts"
                )
            )
            conn.commit()
        _tables_ensured = True
        logger.info("pg_trgm GIN index on langchain_pg_embedding.document ensured")
    except Exception:
        logger.exception("Failed to create pg_trgm index on langchain_pg_embedding.document")
    finally:
        engine.dispose()


def chunks_to_lc_documents(chunks) -> List[Document]:
    """将 Chunk ORM 对象列表转换为 LangChain Document 列表。

    每个 chunk 的 page_content 为文本内容，metadata 包含：
    - chunk_id: chunks 表主键
    - document_id: documents 表主键
    - document_title: 文档标题
    - page_number: 页码
    """
    docs = []
    for c in chunks:
        title = None
        if c.document:
            title = c.document.title or c.document.filename
        docs.append(
            Document(
                page_content=c.content,
                metadata={
                    "chunk_id": c.id,
                    "document_id": c.document_id,
                    "document_title": title or "",
                    "page_number": c.page_number,
                    "generation": getattr(c, "generation", 1) or 1,
                },
            )
        )
    return docs


def vector_id_for_chunk(chunk) -> str:
    generation = getattr(chunk, "generation", 1) or 1
    return (
        f"document-{chunk.document_id}-generation-{generation}-chunk-{chunk.id}"
    )


def add_chunks(store: PGVector, chunks) -> List[str]:
    """将 chunks 向量化并写入 PGVector。

    返回写入的 ID 列表（对应 chunks.id）。
    """
    docs = chunks_to_lc_documents(chunks)
    ids = [vector_id_for_chunk(c) for c in chunks]
    store.add_documents(docs, ids=ids)
    logger.info("Added %d chunks to PGVector collection '%s'", len(docs), store.collection_name)
    return ids


def delete_chunk_vectors(store: PGVector, chunks) -> None:
    """删除代次化向量，同时兼容清理旧版数字 ID。"""
    chunks = list(chunks)
    if not chunks:
        return
    ids = [vector_id_for_chunk(chunk) for chunk in chunks]
    ids.extend(str(chunk.id) for chunk in chunks)
    store.delete(ids=ids)
    logger.info("Deleted vectors for %d business chunks", len(chunks))
