"""M5 内容安全过滤层 — 纯规则匹配，不走 LLM。"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class InputFilterResult:
    blocked: bool = False        # 是否阻断请求
    reason: str = ""             # 阻断原因
    flagged: bool = False        # 是否标记（不阻断，但记录审计）
    flag_reason: str = ""


@dataclass
class DangerResult:
    level: str = ""              # "" | "critical" | "warning"
    advice: str = ""


@dataclass
class OutputFilterResult:
    flagged: bool = False
    flag_reason: str = ""


# ---------------------------------------------------------------------------
# 规则加载
# ---------------------------------------------------------------------------

def _load_json(name: str) -> dict:
    path = _DATA_DIR / name
    if not path.exists():
        logger.warning("Rule file %s not found, using empty rules", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error:
            logger.warning("Invalid regex pattern skipped: %s", p)
    return compiled


# 模块加载时编译
_jailbreak_rules = _load_json("jailbreak_patterns.json")
_symptom_rules = _load_json("dangerous_symptoms.json")

_jailbreak_patterns = _compile_patterns(_jailbreak_rules.get("patterns", []))
_jailbreak_keywords: list[str] = _jailbreak_rules.get("keywords", [])
_medical_inducement_patterns = _compile_patterns(
    _jailbreak_rules.get("medical_inducement_patterns", [])
)

# 危险症状：预编译 (level, compiled_patterns, advice) 三元组
_symptom_triplets: list[tuple[str, list[re.Pattern], str]] = []
for level in ("critical", "warning"):
    for entry in _symptom_rules.get(level, []):
        kw_patterns = entry.get("keywords", [])
        compiled_kw = _compile_patterns(kw_patterns)
        if compiled_kw:
            _symptom_triplets.append((level, compiled_kw, entry.get("advice", "")))


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def filter_input(text: str) -> InputFilterResult:
    """检测用户输入中的越狱/注入/医疗诱导内容。"""
    if not settings.ENABLE_CONTENT_FILTER:
        return InputFilterResult()

    text_lower = text.lower()

    # A. 越狱关键词快速命中
    for kw in _jailbreak_keywords:
        if kw.lower() in text_lower:
            return InputFilterResult(
                blocked=True,
                reason="输入包含不安全内容，已被系统拒绝。",
            )

    # B. 越狱模式匹配
    for pattern in _jailbreak_patterns:
        if pattern.search(text):
            return InputFilterResult(
                blocked=True,
                reason="输入包含不安全内容，已被系统拒绝。",
            )

    # C. 医疗诱导检测（不阻断，仅标记）
    for pattern in _medical_inducement_patterns:
        if pattern.search(text):
            return InputFilterResult(
                flagged=True,
                flag_reason="medical_inducement",
            )

    return InputFilterResult()


def detect_dangerous_symptoms(text: str) -> DangerResult:
    """检测用户输入中是否包含急危重症关键词。"""
    if not settings.ENABLE_DANGER_SYMPTOM_CHECK:
        return DangerResult()

    for level, patterns, advice in _symptom_triplets:
        for pattern in patterns:
            if pattern.search(text):
                return DangerResult(level=level, advice=advice)

    return DangerResult()


def filter_output(text: str) -> OutputFilterResult:
    """检测 LLM 输出中是否包含不应有的确定性诊断或药物剂量。

    当前阶段：仅做简单关键词检测，不修改输出文本。
    """
    if not settings.ENABLE_OUTPUT_FILTER:
        return OutputFilterResult()

    # 确定性诊断句式
    diagnosis_patterns = [
        r"你(患有|得了|确诊了|肯定是).{0,20}(病|症|癌|炎|肿瘤)",
        r"根据.{0,10}(判断|确定|确诊).{0,10}(你|患者)",
    ]
    for pattern in diagnosis_patterns:
        if re.search(pattern, text):
            return OutputFilterResult(
                flagged=True,
                flag_reason="deterministic_diagnosis",
            )

    # 药物剂量信息
    dosage_patterns = [
        r"(每日|每次|一天).{0,5}\d+\s*(次|片|粒|mg|克|毫升)",
        r"(口服|静注|肌注|含服).{0,10}\d+\s*(mg|g|ml)",
    ]
    for pattern in dosage_patterns:
        if re.search(pattern, text):
            return OutputFilterResult(
                flagged=True,
                flag_reason="dosage_info",
            )

    return OutputFilterResult()
