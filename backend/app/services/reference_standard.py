"""参考标准文档 → reference_ranges 结构化解析。"""
import json
import logging
import re

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, ReferenceRange

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*|\d+[.、]\s*)?(?P<name>[A-Za-z][A-Za-z0-9_\-]*)\s*"
    r"(?:[（(](?P<cn>[^）)]*)[)）])?\s*[:：]\s*(?P<range>.*?)\s*$"
)
_UPPER_LT_RE = re.compile(r"<\s*(\d+(?:\.\d+)?)(.*)$")      # 严格上限
_UPPER_LE_RE = re.compile(r"≤\s*(\d+(?:\.\d+)?)(.*)$")      # 含边界上限
_LOWER_GT_RE = re.compile(r">\s*(\d+(?:\.\d+)?)(.*)$")      # 严格下限
_LOWER_GE_RE = re.compile(r"≥\s*(\d+(?:\.\d+)?)(.*)$")      # 含边界下限
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—～]\s*(\d+(?:\.\d+)?)(.*)$")


def _to_number(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_reference_segment(text: str) -> list[dict]:
    """确定性解析单行参考标准，返回 [{indicator_name, name_cn, unit, lower, upper,
    lower_inclusive, upper_inclusive}]。

    支持 "<21 μmol/L"、"3.5-9.5 ×10⁹/L"、"≥140 mmHg"、"≤21 μmol/L" 等格式。
    - 严格边界（<、>）→ 对应 inclusive=False；含边界（≤、≥）与区间 → inclusive=True。
    解析失败返回空列表。字段名与 ReferenceRange 模型一致（indicator_name），
    可直接 **dict 入库。
    """
    m = _LINE_RE.match(text)
    if not m:
        return []
    name = m.group("name")
    cn = m.group("cn") or ""
    rng = m.group("range").strip()
    if not name or not rng:
        return []

    lower = upper = None
    lower_inclusive = True
    upper_inclusive = True
    unit = ""
    m_ult = _UPPER_LT_RE.match(rng)
    m_ule = _UPPER_LE_RE.match(rng)
    m_lgt = _LOWER_GT_RE.match(rng)
    m_lge = _LOWER_GE_RE.match(rng)
    m_r = _RANGE_RE.match(rng)
    if m_ult:
        upper = _to_number(m_ult.group(1))
        upper_inclusive = False
        unit = m_ult.group(2).strip()
    elif m_ule:
        upper = _to_number(m_ule.group(1))
        unit = m_ule.group(2).strip()
    elif m_lgt:
        lower = _to_number(m_lgt.group(1))
        lower_inclusive = False
        unit = m_lgt.group(2).strip()
    elif m_lge:
        lower = _to_number(m_lge.group(1))
        unit = m_lge.group(2).strip()
    elif m_r:
        lower = _to_number(m_r.group(1))
        upper = _to_number(m_r.group(2))
        unit = m_r.group(3).strip()

    if lower is None and upper is None:
        return []
    return [{
        "indicator_name": name,
        "name_cn": cn,
        "unit": unit,
        "lower": lower,
        "upper": upper,
        "lower_inclusive": lower_inclusive,
        "upper_inclusive": upper_inclusive,
    }]


def _extract_json_array(text: str) -> list[dict]:
    """从 LLM 输出中提取 JSON 数组。"""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


_REFERENCE_PARSE_PROMPT = """你是一个医学检验参考范围解析器。从给定的标准文档片段中提取检验指标参考范围。

只输出一个 JSON 数组，不要输出任何其他文字。数组每个元素格式：
{"name": "指标英文缩写", "name_cn": "中文名", "unit": "单位", "lower": 下限数字或null, "upper": 上限数字或null, "lower_inclusive": true或false, "upper_inclusive": true或false, "category": "所属分类"}

规则：
1. 严格上限 "TBIL（总胆红素）：<21 μmol/L" → {"name":"TBIL","name_cn":"总胆红素","unit":"μmol/L","lower":null,"upper":21,"upper_inclusive":false}
2. 含边界上限 "≤21 μmol/L" → upper=21, "upper_inclusive":true
3. 严格下限 ">140 mmHg" → lower=140, "lower_inclusive":false
4. 含边界下限 "≥140 mmHg" → lower=140, "lower_inclusive":true
5. 区间 "WBC：3.5-9.5 ×10⁹/L" → lower=3.5, upper=9.5, 两端 inclusive 均为 true
6. lower 与 upper 至少一个非 null；无法确定范围的条目丢弃
7. 类别从片段所在章节标题推断，如"肝功能指标"
输出必须是可被 json.loads 直接解析的纯 JSON。"""


def _sync_from_llm(chunk_texts: list[str]) -> list[dict]:
    from langchain_openai import ChatOpenAI
    from app.core.config import settings

    llm = ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0,
        max_tokens=2000,
        request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
    )
    combined = "\n\n".join(chunk_texts)
    if len(combined) > 12000:
        combined = combined[:12000]
    from langchain_core.messages import HumanMessage, SystemMessage
    reply = llm.invoke(
        [
            SystemMessage(content=_REFERENCE_PARSE_PROMPT),
            HumanMessage(content=combined),
        ]
    )
    items = _extract_json_array(str(reply.content))
    valid = []
    for it in items:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        try:
            lower = float(it["lower"]) if it.get("lower") is not None else None
            upper = float(it["upper"]) if it.get("upper") is not None else None
        except (TypeError, ValueError):
            continue
        if lower is None and upper is None:
            continue
        valid.append({
            "indicator_name": str(it["name"]).strip()[:100],
            "name_cn": str(it.get("name_cn") or "")[:200],
            "unit": str(it.get("unit") or "")[:50],
            "lower": lower,
            "upper": upper,
            # LLM 路径按 prompt 要求输出 inclusive；缺失时默认含边界（True）。
            # 严格边界（<、>）优先由确定性按行解析路径保留，LLM 只处理其未覆盖的行。
            "lower_inclusive": bool(it.get("lower_inclusive", True)),
            "upper_inclusive": bool(it.get("upper_inclusive", True)),
            "category": str(it.get("category") or "")[:100],
        })
    return valid


def sync_reference_ranges(db: Session, document_id: int) -> dict:
    """同步参考标准文档 → reference_ranges。

    仅允许 access_scope 为 operator/both 的文档被解析，防止把普通聊天
    文档误解析进参考范围。
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"文档 {document_id} 不存在")
    if doc.access_scope not in ("operator", "both"):
        raise ValueError(
            f"文档「{doc.title or doc.filename}」的 access_scope 为 "
            f"'{doc.access_scope}'，仅 operator/both 文档可解析为参考范围"
        )

    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.document_id == document_id,
            Chunk.generation == doc.active_generation,
            Chunk.is_current.is_(True),
        )
        .order_by(Chunk.chunk_index)
        .all()
    )
    if not chunks:
        raise ValueError("文档没有可用的分块，请先完成分块与向量化")

    # 先确定性解析，命中则直接用；未命中的片段交 LLM 提取。
    # 关键：解析必须按【行】进行——parse_reference_segment 是单行解析器，
    # 若对整个多行 chunk 调用，几乎必然失败而整体落入 LLM 路径，丢失 </> 严格边界。
    # 按行拆分后，单行标准（含 <、> 严格边界）由确定性解析精确保留，
    # 只有章节标题等无法确定性解析的行才进 LLM（LLM prompt 也会输出 inclusive）。
    deterministic: list[dict] = []
    llm_fragments: list[str] = []
    for c in chunks:
        lines = [ln.rstrip("\r") for ln in c.content.splitlines() if ln.strip()]
        if not lines:
            continue
        unmatched_lines: list[str] = []
        for ln in lines:
            parsed = parse_reference_segment(ln)
            if parsed:
                deterministic.extend(parsed)
            else:
                unmatched_lines.append(ln)
        if unmatched_lines:
            llm_fragments.append("\n".join(unmatched_lines))

    llm_items: list[dict] = []
    llm_failed = False
    if llm_fragments:
        try:
            llm_items = _sync_from_llm(llm_fragments)
        except Exception:
            llm_failed = True
            logger.exception("LLM reference extraction failed for doc %s", document_id)

    # 失败不破坏旧数据（两层保护）：
    # ① 本应有 LLM 解析的片段失败（llm_fragments 非空且 llm_failed）→ 即使确定性解析
    #    有部分命中，也整体 abort 并保留旧数据——否则参考范围会被静默缩小为部分结果，
    #    同步接口显示成功但后续预测/SSE/PDF 都基于不完整标准。
    if llm_failed and llm_fragments:
        raise ValueError(
            "LLM 提取参考范围失败，已保留文档原有解析结果（不替换为部分数据），请检查后重试"
        )

    items = deterministic + llm_items

    # ② 一条都没解析出来（确定性空）→ 保留旧数据，不提交空集。
    if not items:
        raise ValueError("未能从文档解析出任何参考范围，已保留原有数据")

    # dropped = 本次删除的旧行数（真实删除数量），inserted = 新写入数量。
    # 只有 items 非空且 LLM 全部成功才替换旧行。
    deleted = db.query(ReferenceRange).filter(ReferenceRange.document_id == document_id).delete()
    for it in items:
        db.add(ReferenceRange(document_id=document_id, **it))
    db.commit()
    return {"inserted": len(items), "dropped": deleted, "document_id": document_id}
