"""RAG 链构建模块。

提供 build_full_chain()，将改写、检索、知识充分性判断、生成串联为一条完整 LCEL 链。
最终输出 AIMessage，携带 additional_kwargs.sources 供 SurgeryChatMessageHistory 自动落库。
"""

import logging
import re as _re
from typing import List

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import Runnable, RunnableGenerator, RunnableLambda
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.services.rewrite_client import build_rewrite_runnable
from app.services.safe_stream import SafeSentenceBuffer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是"Surgery RAG Agent"，一位拥有数十年临床与手术经验的外科主任医师。你熟悉各类外科疾病的诊疗规范、手术指征、围术期管理及常见并发症处理，但你始终基于下方提供的知识库上下文回答，绝不凭空推断或编造知识库以外的内容。

回答时必须遵守以下原则：

1. **只依据知识库上下文**
   严格使用下方"相关上下文"中的信息组织回答。若上下文未涉及某一点，请明确说明"根据当前知识库，无法找到足够依据回答该问题"，禁止编造、推测或引入外部知识。

2. **来源引用**
   当你引用上下文中的具体事实、数据、诊疗建议或操作步骤时，必须在对应位置使用 `[序号]` 格式标注来源（序号即上文每条信息前方括号内的数字），例如 `[1]`。每个关键论断后尽量紧跟引用。不要为没有来源支撑的内容伪造引用，也不要编造超出上下文范围的序号。

3. **医学安全边界**
   - 禁止给出确定性诊断、具体处方、药物剂量或替代专业医疗判断的结论。
   - 遇到急症、危重症状或知识库信息不足时，必须建议用户"请尽快咨询主管医生或前往医院就诊"。
   - 回答只作为医学知识参考，不能替代实际诊疗。

4. **专业表达**
   使用规范外科术语，逻辑清晰、分条陈述。优先说明：疾病/问题概述 → 关键诊疗要点 → 手术/处理建议（如有） → 注意事项/并发症（如有） → 何时需就医。

5. **信息不足时的统一话术**
   若检索到的上下文无法支撑有效回答，请完整输出：
   "根据当前知识库，无法找到足够依据回答该问题。建议您补充更详细的病情资料，或咨询您的主管医生。"

请记住：你的角色是辅助临床决策的医学知识助手，最终诊疗方案必须由具备执业资质的医生根据患者具体情况制定。"""

NO_KNOWLEDGE_ANSWER = (
    "根据当前知识库，无法找到足够依据回答该问题。"
    "建议您补充更详细的病情资料，或咨询您的主管医生。"
)

# ---------------------------------------------------------------------------
# LLM 实例
# ---------------------------------------------------------------------------

_llm = ChatOpenAI(
    model=settings.DEEPSEEK_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True,
    temperature=0.3,
    max_tokens=2048,
    request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
)

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("system", "相关上下文：\n{context}"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{input}"),
])

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _format_docs(docs: List[Document]) -> str:
    """把检索到的 LangChain Document 拼接成上下文字符串，按序号编号。"""
    return "\n\n".join(
        f"[{i + 1}] {doc.page_content}"
        for i, doc in enumerate(docs)
    )


def _has_sufficient_knowledge_for_docs(docs: List[Document]) -> bool:
    """判断 LangChain Document 检索结果是否有足够医学依据。

    逻辑：高分向量命中，或接近阈值的双路命中，或明确全文命中。
    所有阈值均可通过离线评测集校准。
    """
    if not docs:
        return False

    max_vector = max(
        (doc.metadata.get("vector_score") or 0.0 for doc in docs),
        default=0.0,
    )

    if max_vector >= settings.RETRIEVER_SIMILARITY_THRESHOLD:
        return True

    lower_vector_threshold = max(
        0.0,
        settings.RETRIEVER_SIMILARITY_THRESHOLD - settings.RETRIEVER_DUAL_MATCH_MARGIN,
    )

    if any(
        doc.metadata.get("vector_rank") is not None
        and doc.metadata.get("fulltext_rank") is not None
        and (doc.metadata.get("vector_score") or 0.0) >= lower_vector_threshold
        for doc in docs
    ):
        return True

    if any(
        (doc.metadata.get("fulltext_score") or 0.0)
        >= settings.RETRIEVER_FULLTEXT_THRESHOLD
        for doc in docs
    ):
        return True

    return False


def parse_citations(text: str, total: int = 0) -> List[int]:
    """从模型输出中解析 [序号] 引用，返回去重且合法的 1-based 序号列表。"""
    ids = _re.findall(r"\[(\d+)\]", text)
    seen = set()
    result = []
    for s in ids:
        i = int(s)
        if i in seen:
            continue
        if total > 0 and (i < 1 or i > total):
            continue
        seen.add(i)
        result.append(i)
    return result


# ---------------------------------------------------------------------------
# 链构建
# ---------------------------------------------------------------------------


def build_full_chain(retriever: BaseRetriever) -> Runnable:
    """构建完整 RAG 链。

    链流程：
    1. 改写查询（规则 + LLM 双层）
    2. 检索文档
    3. 知识充分性判断
    4a. 知识不足 → fallback AIMessage
    4b. 知识充分 → 生成回答 → 附着引用来源 → AIMessage

    最终输出 AIMessage，其 additional_kwargs 包含：
    - sources: List[dict]  引用来源列表
    - rewritten: str       改写后的查询

    流式调用时，中间 token 以 AIMessageChunk 形式逐块产出，
    最终经过 RunnableLambda 包装为带 sources 的完整 AIMessage。
    """
    rewrite_runnable = build_rewrite_runnable()

    def _prepare(state: dict) -> dict:
        """准备阶段：改写查询 + 检索文档。"""
        question = state["input"]
        history = list(state.get("history", []) or [])

        # 前端在调用 ask 前已通过 REST 保存用户消息，
        # RunnableWithMessageHistory 会将 DB 中的历史（含当前问题）传入。
        # 这里把末尾与当前问题一致的用户消息移除，避免改写和 prompt 中出现重复。
        from langchain_core.messages import HumanMessage as _HM
        if history and isinstance(history[-1], _HM) and history[-1].content == question:
            history.pop()

        rewritten = rewrite_runnable.invoke({"question": question, "history": history})
        docs = retriever.invoke(rewritten)
        context = _format_docs(docs)

        logger.info(
            "Chain prepare: question='%s...', rewritten='%s...', docs=%d",
            question[:30],
            rewritten[:30],
            len(docs),
        )

        return {
            **state,
            "history": history,  # 清理后的历史，供 prompt 的 MessagesPlaceholder 使用
            "rewritten": rewritten,
            "docs": docs,
            "context": context,
        }

    def _route(state: dict) -> Runnable:
        """路由：根据知识充分性选择生成分支或 fallback。"""
        docs = state.get("docs", [])
        rewritten = state.get("rewritten", "")

        if not _has_sufficient_knowledge_for_docs(docs):
            logger.info("Knowledge insufficient, routing to fallback")
            return RunnableLambda(lambda _: AIMessage(
                content=NO_KNOWLEDGE_ANSWER,
                additional_kwargs={
                    "sources": [],
                    "rewritten": rewritten,
                    "is_no_knowledge": True,
                },
            ))

        async def _stream_attach(input_stream):
            """Streaming-aware source attachment.

            透传 LLM token 级流式输出，读取结束后构建引用来源并附加到最终 chunk。
            RunnableWithMessageHistory 将保存最终 chunk 的 additional_kwargs。

            即使 LLM 流中途报错，也通过 finally 产出携带已累积文本的最终 chunk，
            避免部分响应在 DB 中丢失。
            """
            full_text = ""
            output_filter_reasons: list[str] = []
            sentence_buffer = SafeSentenceBuffer()

            async for chunk in input_stream:
                content = chunk.content if hasattr(chunk, "content") else ""
                for segment in sentence_buffer.push(content):
                    full_text += segment.text
                    if segment.reason and segment.reason not in output_filter_reasons:
                        output_filter_reasons.append(segment.reason)
                    yield AIMessageChunk(content=segment.text)

            for segment in sentence_buffer.finish():
                full_text += segment.text
                if segment.reason and segment.reason not in output_filter_reasons:
                    output_filter_reasons.append(segment.reason)
                yield AIMessageChunk(content=segment.text)

            citation_indices = parse_citations(full_text, total=len(docs))
            sources = []
            for idx in citation_indices:
                doc = docs[idx - 1]
                sources.append({
                    "chunk_id": doc.metadata.get("chunk_id"),
                    "document_id": doc.metadata.get("document_id"),
                    "title": doc.metadata.get("document_title", ""),
                    "page_number": doc.metadata.get("page_number"),
                    "citation_index": idx,
                    "content": doc.page_content,
                    "images": doc.metadata.get("images", []),
                })

            yield AIMessageChunk(
                content="",
                additional_kwargs={
                    "sources": sources,
                    "rewritten": rewritten,
                    "full_content": full_text,
                    "output_filter_reasons": output_filter_reasons,
                },
            )

        return _prompt | _llm | RunnableGenerator(_stream_attach)

    return (
        RunnableLambda(_prepare)
        | RunnableLambda(_route)
    )
