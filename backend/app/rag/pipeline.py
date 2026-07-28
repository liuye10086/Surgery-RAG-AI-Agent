import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.models import Chunk, Document as DocumentModel
from app.services.embedder import embed_texts

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """检索结果封装。"""

    chunk: Chunk
    score: float  # 综合得分（RRF 分数），仅用于排序
    vector_score: Optional[float] = None  # 向量余弦相似度
    vector_rank: Optional[int] = None
    fulltext_score: Optional[float] = None
    fulltext_rank: Optional[int] = None


class SurgeryRetriever(BaseRetriever):
    """LangChain Retriever 包装已有的 hybrid search。"""

    db: Session
    top_k: int = settings.RETRIEVER_FINAL_TOP_K
    department_id: Optional[int] = None

    def _get_relevant_documents(self, query: str) -> List[Document]:
        results = hybrid_search(
            self.db,
            query,
            top_k=self.top_k,
            department_id=self.department_id,
        )
        return [
            Document(
                page_content=rc.chunk.content,
                metadata={
                    "chunk_id": rc.chunk.id,
                    "document_id": rc.chunk.document_id,
                    "document_title": rc.chunk.document.title,
                    "page_number": rc.chunk.page_number,
                    "vector_score": rc.vector_score,
                    "vector_rank": rc.vector_rank,
                    "fulltext_score": rc.fulltext_score,
                    "fulltext_rank": rc.fulltext_rank,
                    "images": (rc.chunk.chunk_metadata or {}).get("images", []),
                },
            )
            for rc in results
        ]


def _vector_search(
    db: Session,
    query: str,
    top_k: int,
    department_id: Optional[int] = None,
) -> List[RetrievedChunk]:
    """基于 pgvector 的余弦相似度检索。

    查询 LangChain PGVector 的 langchain_pg_embedding 表，
    通过 id 关联回业务 chunks 表。
    当 department_id 不为 None 时，仅检索该科室文档。
    """
    embeddings = embed_texts([query])
    if not embeddings or not embeddings[0]:
        return []

    query_embedding = embeddings[0]
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    sql = text(
        """
        SELECT e.cmetadata->>'chunk_id' AS chunk_id,
               e.embedding <=> CAST(:embedding AS vector) AS distance
        FROM langchain_pg_embedding e
        JOIN langchain_pg_collection c ON c.uuid = e.collection_id
        JOIN chunks business_chunk
          ON business_chunk.id = CAST(e.cmetadata->>'chunk_id' AS INTEGER)
        JOIN documents business_document
          ON business_document.id = business_chunk.document_id
        WHERE c.name = :coll_name
          AND business_chunk.is_current IS TRUE
          AND business_chunk.generation = business_document.active_generation
          AND business_document.is_current IS TRUE
          AND (:dept_id IS NULL OR business_document.department_id = :dept_id)
        ORDER BY distance ASC
        LIMIT :top_k
        """
    )
    rows = db.execute(
        sql,
        {
            "embedding": embedding_str,
            "coll_name": settings.VECTOR_COLLECTION_NAME,
            "top_k": top_k,
            "dept_id": department_id,
        },
    ).fetchall()
    if not rows:
        return []

    chunk_ids = [int(r[0]) for r in rows if r[0] is not None]
    distances = {int(r[0]): float(r[1]) for r in rows if r[0] is not None}

    chunks = (
        db.query(Chunk)
        .options(joinedload(Chunk.document))
        .join(DocumentModel, DocumentModel.id == Chunk.document_id)
        .filter(
            Chunk.id.in_(chunk_ids),
            Chunk.is_current.is_(True),
            Chunk.generation == DocumentModel.active_generation,
            DocumentModel.is_current.is_(True),
        )
        .all()
    )
    # 保持向量检索的排序
    order = {cid: idx for idx, cid in enumerate(chunk_ids)}
    chunks.sort(key=lambda c: order[c.id])

    return [
        RetrievedChunk(
            chunk=c,
            score=0.0,
            vector_score=1.0 - distances[c.id],
            vector_rank=order[c.id] + 1,
        )
        for c in chunks
    ]


def _fulltext_search(
    db: Session,
    query: str,
    top_k: int,
    department_id: Optional[int] = None,
) -> List[RetrievedChunk]:
    """基于 pg_trgm 相似度检索 langchain_pg_embedding.document 列。

    使用 pg_trgm 的 similarity() 函数替代 tsvector/tsquery，
    以支持中文等无空格分隔语言。GIN 索引使用 gin_trgm_ops。
    当 department_id 不为 None 时，仅检索该科室文档。
    """
    if not query or not query.strip():
        return []

    sql = text(
        """
        SELECT
            e.cmetadata->>'chunk_id' AS chunk_id,
            GREATEST(
                similarity(e.document, :query),
                similarity(COALESCE(e.cmetadata->>'document_title', ''), :query)
            ) AS text_score
        FROM langchain_pg_embedding e
        JOIN langchain_pg_collection c ON c.uuid = e.collection_id
        JOIN chunks business_chunk
          ON business_chunk.id = CAST(e.cmetadata->>'chunk_id' AS INTEGER)
        JOIN documents business_document
          ON business_document.id = business_chunk.document_id
        WHERE c.name = :coll_name
          AND business_chunk.is_current IS TRUE
          AND business_chunk.generation = business_document.active_generation
          AND business_document.is_current IS TRUE
          AND (:dept_id IS NULL OR business_document.department_id = :dept_id)
          AND GREATEST(
                similarity(e.document, :query),
                similarity(COALESCE(e.cmetadata->>'document_title', ''), :query)
              ) > 0.0
        ORDER BY text_score DESC
        LIMIT :top_k
        """
    )
    rows = db.execute(
        sql,
        {
            "query": query,
            "coll_name": settings.VECTOR_COLLECTION_NAME,
            "top_k": top_k,
            "dept_id": department_id,
        },
    ).fetchall()
    if not rows:
        return []

    chunk_ids = [int(r[0]) for r in rows if r[0] is not None]
    text_scores = {int(r[0]): float(r[1]) for r in rows if r[0] is not None}
    if not chunk_ids:
        return []

    chunks = (
        db.query(Chunk)
        .options(joinedload(Chunk.document))
        .join(DocumentModel, DocumentModel.id == Chunk.document_id)
        .filter(
            Chunk.id.in_(chunk_ids),
            Chunk.is_current.is_(True),
            Chunk.generation == DocumentModel.active_generation,
            DocumentModel.is_current.is_(True),
        )
        .all()
    )
    # 保持全文检索的 similarity 排序（与 _vector_search 一致的修复）
    order = {cid: idx for idx, cid in enumerate(chunk_ids)}
    chunks.sort(key=lambda c: order.get(c.id, len(chunk_ids)))
    return [
        RetrievedChunk(
            chunk=chunk,
            score=0.0,
            fulltext_score=text_scores[chunk.id],
            fulltext_rank=order[chunk.id] + 1,
        )
        for chunk in chunks
    ]


def _rrf_fuse(
    vector_results: List[RetrievedChunk],
    fulltext_results: List[RetrievedChunk],
    final_top_k: int,
    k: int = 60,
) -> List[RetrievedChunk]:
    """Reciprocal Rank Fusion 融合向量与全文结果。"""
    scores: defaultdict[int, float] = defaultdict(float)
    vector_lookup: dict[int, RetrievedChunk] = {rc.chunk.id: rc for rc in vector_results}

    for rank, rc in enumerate(vector_results, start=1):
        scores[rc.chunk.id] += 1.0 / (k + rank)

    for rank, rc in enumerate(fulltext_results, start=1):
        chunk_id = rc.chunk.id
        scores[chunk_id] += 1.0 / (k + rank)
        if chunk_id not in vector_lookup:
            vector_lookup[chunk_id] = rc
        else:
            vector_lookup[chunk_id].fulltext_score = rc.fulltext_score
            vector_lookup[chunk_id].fulltext_rank = rc.fulltext_rank

    sorted_ids = sorted(scores, key=scores.get, reverse=True)[:final_top_k]
    return [
        RetrievedChunk(
            chunk=vector_lookup[cid].chunk,
            score=scores[cid],
            vector_score=vector_lookup[cid].vector_score,
            vector_rank=vector_lookup[cid].vector_rank,
            fulltext_score=vector_lookup[cid].fulltext_score,
            fulltext_rank=vector_lookup[cid].fulltext_rank,
        )
        for cid in sorted_ids
    ]


def hybrid_search(
    db: Session,
    query: str,
    top_k: int = settings.RETRIEVER_FINAL_TOP_K,
    department_id: Optional[int] = None,
) -> List[RetrievedChunk]:
    """混合检索入口：向量 + 全文 + RRF 融合。

    Args:
        db: SQLAlchemy Session。
        query: 用户查询。
        top_k: 最终返回片段数。
        department_id: 可选科室筛选，为 None 时搜索全部文档。

    Returns:
        按 RRF 得分降序排列的 RetrievedChunk 列表。
    """
    if not query or not query.strip():
        return []

    # 各分支独立容错：单个分支失败不影响另一分支的结果
    vector_results: list = []
    fulltext_results: list = []
    vector_failed = False
    fulltext_failed = False

    try:
        vector_results = _vector_search(
            db, query, settings.RETRIEVER_TOP_K_VECTOR, department_id=department_id,
        )
    except Exception:
        vector_failed = True
        logger.exception("Vector search failed for query '%s...'", query[:30])

    try:
        fulltext_results = _fulltext_search(
            db, query, settings.RETRIEVER_TOP_K_FULLTEXT, department_id=department_id,
        )
    except Exception:
        fulltext_failed = True
        logger.exception("Fulltext search failed for query '%s...'", query[:30])

    if not vector_results and not fulltext_results:
        if vector_failed and fulltext_failed:
            raise RuntimeError(
                f"Both vector and fulltext search failed for query '{query[:30]}...'"
            )
        return []

    fused = _rrf_fuse(
        vector_results,
        fulltext_results,
        final_top_k=top_k,
        k=settings.RETRIEVER_FUSION_K,
    )

    logger.info(
        "Hybrid search for query '%s...' returned %d chunks (vector=%d, fulltext=%d)",
        query[:30],
        len(fused),
        len(vector_results),
        len(fulltext_results),
    )
    return fused
