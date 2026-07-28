"""AI 操作者报告生成服务。

提供 generate_report() 异步生成器，产出 SSE 事件流。
由 operator.py（API 层）负责创建 ai_reports 记录并传入 report_id，
本 service 只负责检索、LLM 生成和更新该记录。

多科室检索合并策略：
  1. 单科/全库 → hybrid_search(top_k=20, department_id=...)
  2. 多科室   → 每科 hybrid_search(top_k=15) → chunk.id 去重 → RRF score 降序 → 截断 top 20
"""

import json
import logging
import time as _time
from datetime import datetime, timezone
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIReport, Department
from app.rag.pipeline import hybrid_search, RetrievedChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_REPORT_SYSTEM_PROMPT = """你是一位资深医学数据分析师，专注于从外科临床病例知识库中提取规律、发现模式。
你的任务是基于检索到的知识库片段，生成一份结构化的医学分析报告。

## 报告结构要求

你必须按照以下 7 章结构生成报告，使用 Markdown 格式：

## 1. 报告摘要
（200 字以内的核心发现概述，提炼最重要的发现）

## 2. 研究问题
（复述用户的分析问题，明确分析范围）

## 3. 数据来源
（此章节由系统自动填充，不要生成内容，保留占位标记：[数据来源由系统填充]）

## 4. 数据分析与发现
（按主题分条呈现关键发现，每条附 [序号] 引用，序号对应上文检索片段前方括号内的数字）

## 5. 检索样本中的观察性特征
（从本次检索到的片段中归纳共性特征、模式、趋势等）
**必须明确标注：基于检索样本，非全量数据库统计，仅供参考**

## 6. 讨论
（发现的临床意义、局限性、与现有知识的关联）

## 7. 结论与建议
（总结性陈述）

## 重要原则

1. **只依据检索上下文**：严格使用提供的知识库片段组织报告。若某方面无上下文支撑，注明"当前检索样本中未发现相关信息"。
2. **来源引用**：引用具体事实时使用 `[序号]` 标注来源，不得伪造引用。
3. **医学安全边界**：报告末尾必须包含免责声明——"本报告由 AI 基于知识库自动生成，仅供参考，不构成临床决策依据。"
4. **专业表达**：使用规范医学术语，逻辑清晰。
5. **数据局限性**：第 5 章必须标注"基于检索样本，非全量数据库统计，仅供参考"。"""

_NO_CONTEXT_REPORT = """## 1. 报告摘要
当前知识库中未检索到与问题相关的足够信息，无法生成有意义的分析报告。

## 2. 研究问题
{query}

## 3. 数据来源
[数据来源由系统填充]

## 4. 数据分析与发现
当前检索样本中未发现相关信息。

## 5. 检索样本中的观察性特征
基于检索样本，非全量数据库统计，仅供参考：本次检索未获取到有效知识库片段，无法归纳观察性特征。

## 6. 讨论
建议扩大检索范围、更换关键词或补充相关知识库文档后重新生成。

## 7. 结论与建议
本报告由 AI 基于知识库自动生成，仅供参考，不构成临床决策依据。"""

_CHAPTER_BOUNDARIES = [
    "## 1. 报告摘要",
    "## 2. 研究问题",
    "## 3. 数据来源",
    "## 4. 数据分析与发现",
    "## 5. 检索样本中的观察性特征",
    "## 6. 讨论",
    "## 7. 结论与建议",
]

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _validate_department_ids(
    db: Session, department_ids: Optional[list[int]]
) -> Optional[list[int]]:
    """校验科室 ID 列表的有效性。

    Returns:
        校验通过的科室 ID 列表，或 None（全库检索）。
    Raises:
        ValueError: 存在无效或已停用的科室 ID。
    """
    if not department_ids:
        return None
    depts = (
        db.query(Department)
        .filter(
            Department.id.in_(department_ids),
            Department.is_active.is_(True),
        )
        .all()
    )
    found_ids = {d.id for d in depts}
    invalid = [did for did in department_ids if did not in found_ids]
    if invalid:
        raise ValueError(f"无效或已停用的科室 ID: {invalid}")
    return department_ids


def _retrieve_for_report(
    db: Session,
    query: str,
    department_ids: Optional[list[int]],
) -> list[RetrievedChunk]:
    """多科室检索：去重 + RRF 合并 + 截断 top 20。"""
    if not department_ids or len(department_ids) == 0:
        return hybrid_search(db, query, top_k=20, department_id=None)

    if len(department_ids) == 1:
        return hybrid_search(
            db, query, top_k=20, department_id=department_ids[0]
        )

    # 多科室：每科室 15 → 去重 → RRF 排序 → top 20
    seen: dict[int, RetrievedChunk] = {}
    for dept_id in department_ids:
        try:
            results = hybrid_search(db, query, top_k=15, department_id=dept_id)
            for rc in results:
                cid = rc.chunk.id
                if cid not in seen or rc.score > seen[cid].score:
                    seen[cid] = rc
        except Exception:
            logger.exception(
                "Retrieval failed for department_id=%s, query='%s...'",
                dept_id,
                query[:30],
            )
            continue

    merged = sorted(seen.values(), key=lambda rc: rc.score, reverse=True)
    return merged[:20]


def _format_docs(docs: list[RetrievedChunk]) -> str:
    """检索结果 → LLM 上下文字符串。"""
    return "\n\n".join(
        f"[{i + 1}] {rc.chunk.content}"
        for i, rc in enumerate(docs)
    )


def _build_sources(docs: list[RetrievedChunk]) -> list[dict]:
    """检索结果 → sources JSON。"""
    return [
        {
            "chunk_id": rc.chunk.id,
            "document_id": rc.chunk.document_id,
            "title": rc.chunk.document.title if rc.chunk.document else "",
            "page_number": rc.chunk.page_number,
            "citation_index": i + 1,
            "content": rc.chunk.content[:500],
        }
        for i, rc in enumerate(docs)
    ]


def _extract_title(full_content: str, query: str) -> str:
    """从报告内容提取标题（第一个 # 级标题），回退到 query 截断。"""
    for line in full_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            if title:
                return title[:500]
    return query[:500]


def _sse(event: str, data: dict) -> str:
    """构建单条 SSE 消息。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _hit_boundary(full_content: str) -> bool:
    """检查最新内容是否刚好到达章节边界。"""
    stripped = full_content.rstrip()
    for boundary in _CHAPTER_BOUNDARIES:
        if stripped.endswith(boundary):
            return True
    return False


# ---------------------------------------------------------------------------
# LLM 实例
# ---------------------------------------------------------------------------

_llm = ChatOpenAI(
    model=settings.DEEPSEEK_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True,
    temperature=0.2,
    max_tokens=4096,
    request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
)

_prompt = ChatPromptTemplate.from_messages([
    ("system", _REPORT_SYSTEM_PROMPT),
    ("system", "检索上下文：\n{context}"),
    ("human", "请基于以上检索上下文，就以下问题生成分析报告：\n{query}"),
])


# ---------------------------------------------------------------------------
# 主入口：SSE 事件流生成器
# ---------------------------------------------------------------------------


async def generate_report(
    db: Session,
    user_id: int,
    report_id: int,
    query: str,
    department_ids: Optional[list[int]] = None,
    analysis_backend: str = "llm",
):
    """生成报告的主入口，产出 SSE 事件流。

    由 operator.py 调用方负责：
    1. 创建 ai_reports 记录（status=generating）
    2. 传入 db、user_id、report_id
    3. 在 finally 中处理断连/取消的状态标记

    Yields:
        SSE 格式字符串（stage / delta / sources / done / error 事件）。
    """
    if analysis_backend != "llm":
        _persist_failed(db, report_id, "", f"未知的 analysis_backend: {analysis_backend}")
        yield _sse("error", {"error": f"未知的 analysis_backend: {analysis_backend}"})
        return

    # 1. 校验科室
    try:
        valid_dept_ids = _validate_department_ids(db, department_ids)
    except ValueError as e:
        _persist_failed(db, report_id, "", str(e))
        yield _sse("error", {"error": str(e)})
        return

    # 2. 检索阶段
    yield _sse("stage", {"stage": "retrieving", "message": "正在检索知识库..."})

    docs = _retrieve_for_report(db, query, valid_dept_ids)

    if not docs:
        logger.warning(
            "No documents retrieved for report %s, query='%s...'",
            report_id,
            query[:30],
        )
        # 无检索结果时产出 fallback 报告
        full_content = _NO_CONTEXT_REPORT.format(query=query)
        for line in full_content.split("\n"):
            yield _sse("delta", {"content": line + "\n"})
        _persist_completed(db, report_id, full_content, [], {})
        yield _sse("sources", {"sources": []})
        yield _sse("done", {"report_id": report_id})
        return

    yield _sse(
        "stage",
        {"stage": "retrieved", "message": f"检索完成，找到 {len(docs)} 个相关片段"},
    )

    # 3. 更新检索元数据到 DB
    sources = _build_sources(docs)
    dept_names = _resolve_department_names(db, valid_dept_ids)
    doc_ids = list({rc.chunk.document_id for rc in docs})
    chunk_ids = [rc.chunk.id for rc in docs]

    retrieval_meta = {
        "original_query": query,
        "rewritten_query": None,
        "department_ids": valid_dept_ids or [],
        "department_names": dept_names,
        "per_department_top_k": (
            15 if valid_dept_ids and len(valid_dept_ids) > 1 else 20
        ),
        "final_top_k": len(docs),
        "retrieved_chunk_ids": chunk_ids,
        "document_count": len(doc_ids),
        "chunk_count": len(docs),
        "model_name": settings.DEEPSEEK_MODEL,
        "temperature": 0.2,
        "max_tokens": 4096,
        "generation_started_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_meta(db, report_id, sources, retrieval_meta)

    yield _sse("stage", {"stage": "generating", "message": "正在生成分析报告..."})

    # 4. 流式 LLM 生成 + SSE 输出 + 定期持久化
    context = _format_docs(docs)
    chain = _prompt | _llm

    full_content = ""
    last_persist = _time.monotonic()
    PERSIST_INTERVAL = 30  # 秒

    try:
        async for chunk in chain.astream({"context": context, "query": query}):
            content = chunk.content if hasattr(chunk, "content") else ""
            if content:
                full_content += content
                yield _sse("delta", {"content": content})

                now = _time.monotonic()
                if _hit_boundary(full_content) or (now - last_persist) >= PERSIST_INTERVAL:
                    _persist_content(db, report_id, full_content)
                    last_persist = now
    except Exception as exc:
        logger.exception("LLM stream failed for report %s", report_id)
        _persist_failed(db, report_id, full_content, str(exc))
        yield _sse("error", {"error": "报告生成过程中发生错误"})
        return

    # 5. 完成
    retrieval_meta["generation_completed_at"] = datetime.now(timezone.utc).isoformat()
    title = _extract_title(full_content, query)
    _persist_completed(db, report_id, full_content, sources, retrieval_meta, title)
    yield _sse("sources", {"sources": sources})
    yield _sse("done", {"report_id": report_id})


# ---------------------------------------------------------------------------
# 持久化辅助函数
# ---------------------------------------------------------------------------


def _resolve_department_names(
    db: Session, department_ids: Optional[list[int]]
) -> list[str]:
    """解析科室 ID → 名称列表。"""
    if not department_ids:
        return []
    depts = (
        db.query(Department)
        .filter(Department.id.in_(department_ids))
        .all()
    )
    return [d.name for d in depts]


def _persist_meta(
    db: Session, report_id: int, sources: list[dict], meta: dict
) -> None:
    """写入检索元数据和 sources。"""
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report:
        report.sources = sources
        report.retrieval_meta = meta
        db.commit()


def _persist_content(db: Session, report_id: int, content: str) -> None:
    """节流写入 content。"""
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report:
        report.content = content
        db.commit()


def _persist_completed(
    db: Session,
    report_id: int,
    content: str,
    sources: list[dict],
    retrieval_meta: dict,
    title: Optional[str] = None,
) -> None:
    """标记报告为完成（仅 generating → completed）。"""
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report and report.status == "generating":
        report.content = content
        report.sources = sources
        report.retrieval_meta = retrieval_meta
        report.status = "completed"
        if title:
            report.title = title
        db.commit()


def _persist_failed(
    db: Session, report_id: int, partial_content: str, error: str
) -> None:
    """标记报告为失败，保留已生成内容（仅 generating → failed）。"""
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report and report.status == "generating":
        if partial_content:
            report.content = partial_content
        report.status = "failed"
        report.error_message = error
        db.commit()
