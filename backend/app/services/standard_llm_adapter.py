"""DeepSeek adapter for review-only standard parsing candidates.

This module shares the project's DeepSeek settings but keeps standard parsing
isolated from the conversational chain. The client is created lazily so merely
importing the admin API never requires an API key or performs network I/O.
"""

from __future__ import annotations

import json
from typing import Any


STANDARD_CANDIDATE_SYSTEM_PROMPT = """你是医学标准规则解析器。只从给定标准片段中提取一个可审核的规则候选，不要做医学推断。
只输出一个 JSON 对象，字段包括：indicator_name、rule_type、target_state_type、target_state_value、
machine_actionability、evidence_type、applicability、interpretation、numeric。
numeric 必须是 null 或对象 {lower, upper, lower_inclusive, upper_inclusive, unit}。
无法可靠计算的方向性、影像、研究阈值或缺少适用条件的内容必须标记 machine_actionability 为 evidence-only。
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.startswith("json"):
            value = value[4:].strip()
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(value[start : end + 1])
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_candidate_output(raw_output: str, *, model_name: str = "deepseek-chat") -> dict[str, Any] | None:
    parsed = _extract_json(raw_output)
    if parsed is None or not parsed.get("indicator_name"):
        return None
    numeric = parsed.get("numeric")
    if numeric is None and any(key in parsed for key in ("lower", "upper", "unit", "lower_inclusive", "upper_inclusive")):
        numeric = {
            "lower": parsed.get("lower"),
            "upper": parsed.get("upper"),
            "lower_inclusive": parsed.get("lower_inclusive", True),
            "upper_inclusive": parsed.get("upper_inclusive", True),
            "unit": parsed.get("unit") or "",
        }
    if numeric is not None and not isinstance(numeric, dict):
        numeric = None
    result = {
        "indicator_name": str(parsed.get("indicator_name", "")).strip()[:200],
        "rule_type": str(parsed.get("rule_type") or "qualitative_direction"),
        "target_state_type": str(parsed.get("target_state_type") or "evidence"),
        "target_state_value": parsed.get("target_state_value"),
        "machine_actionability": parsed.get("machine_actionability") if parsed.get("machine_actionability") in {"calculable", "evidence-only", "blocked"} else "evidence-only",
        "evidence_type": parsed.get("evidence_type") or "llm_candidate",
        "applicability": parsed.get("applicability") if isinstance(parsed.get("applicability"), dict) else {},
        "interpretation": parsed.get("interpretation"),
        "numeric": numeric,
        "_raw_output": raw_output,
        "_model_name": model_name,
    }
    return result


class DeepSeekStandardCandidateAdapter:
    model_name = "deepseek-chat"

    def __init__(self, llm=None):
        self._llm = llm

    def _client(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            from app.core.config import settings

            self._llm = ChatOpenAI(
                model=settings.DEEPSEEK_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                streaming=False,
                temperature=0,
                max_tokens=1200,
                request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
            )
            self.model_name = settings.DEEPSEEK_MODEL
        return self._llm

    def __call__(self, segment_text: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        from langchain_core.messages import HumanMessage, SystemMessage

        context = context or {}
        prompt = f"上下文：{json.dumps(context, ensure_ascii=False)}\n标准片段：\n{segment_text}"
        try:
            reply = self._client().invoke([
                SystemMessage(content=STANDARD_CANDIDATE_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return normalize_candidate_output(str(reply.content), model_name=self.model_name)
        except Exception:
            return None


def create_deepseek_standard_candidate_adapter():
    return DeepSeekStandardCandidateAdapter()


__all__ = ["DeepSeekStandardCandidateAdapter", "create_deepseek_standard_candidate_adapter", "normalize_candidate_output"]
