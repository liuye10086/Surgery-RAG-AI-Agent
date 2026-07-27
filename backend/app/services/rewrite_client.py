import logging

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是“Surgery RAG Agent”的查询改写专家，擅长把医患连续对话中的省略、指代和缩写补全为一条完整、独立、可用于医学知识库检索的查询。

任务：
根据提供的对话历史，把“当前问题”改写为一条自包含的检索查询。不要回答问题，只输出改写后的查询。

改写规则：
1. **指代消解**：若当前问题用“它、这、那、该、这个、那个、这种疾病、该手术”等指代前文内容，请替换为具体医学实体。
2. **省略补全**：若当前问题缺少主语或关键医学实体，请根据历史对话补全。
3. **缩写还原**：若当前问题出现医学缩写（如 LC、TACE、ERCP 等），请根据上下文还原为全称或明确含义。
4. **保持原意**：不要改变用户问题的原意，不要添加问题以外的推测性内容。
5. **医学术语规范**：使用标准外科/医学术语，避免口语化表达。
6. **输出格式**：只输出一条改写后的查询，不要解释、不要有多余内容。

示例：
历史：
用户：胆囊结石的治疗方法
助手：...
用户：LC 术后饮食要注意什么？

当前问题：有哪些忌口？

改写后：腹腔镜胆囊切除术后饮食有哪些忌口？"""


def build_rewrite_runnable() -> Runnable:
    """构建查询改写 LCEL 子链。

    先执行规则层中文指代消解，若未命中且配置开启则调用 LLM 补全省略和缩写。
    输入：{"question": str, "history": List[BaseMessage]}
    输出：改写后的查询字符串。
    """
    # LLM 改写子链（仅在规则未命中且配置开启时使用）
    _rewrite_prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="history"),
        ("human", "当前问题：{question}\n\n改写后的查询："),
    ])

    _rewrite_llm = ChatOpenAI(
        model=settings.REWRITE_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        streaming=False,
        temperature=0.1,
        max_tokens=256,
        request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
    )

    _llm_chain: Runnable | None = (
        _rewrite_prompt | _rewrite_llm | StrOutputParser()
        if settings.ENABLE_LLM_QUERY_REWRITE
        else None
    )

    def _do_rewrite(state: dict) -> str:
        """执行改写：规则优先 → LLM 降级。"""
        query = state.get("question", "").strip()
        history = state.get("history", []) or []

        if not query:
            return query

        if not history:
            return query

        # 第一层：规则改写（中文指代消解）
        vague_prefixes = ("它", "这", "那", "该", "这个", "那个", "这个疾病", "该疾病")
        if query.startswith(vague_prefixes):
            for msg in reversed(history):
                if isinstance(msg, HumanMessage):
                    entity = msg.content.rstrip("？?")
                    rewritten = f"{entity}，{query}"
                    logger.info(
                        "Rule rewrite: '%s...' -> '%s...'", query[:30], rewritten[:30]
                    )
                    return rewritten

        # 第二层：LLM 改写
        if _llm_chain is not None:
            try:
                rewritten = _llm_chain.invoke(
                    {"question": query, "history": history}
                )
                if rewritten and rewritten.strip() != query:
                    logger.info(
                        "LLM rewrite: '%s...' -> '%s...'",
                        query[:30],
                        rewritten[:30],
                    )
                    return rewritten.strip()
            except Exception:
                logger.warning("LLM query rewrite failed, using original")

        return query

    return RunnableLambda(_do_rewrite)
