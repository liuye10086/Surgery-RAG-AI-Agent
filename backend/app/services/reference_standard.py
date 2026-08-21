"""参考标准文档 → reference_ranges 结构化解析。"""
import json
import logging
import re
from pathlib import Path

from docx import Document as DocxDocument
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, ReferenceRange

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*|\d+[.、]\s*)?(?P<name>[A-Za-z][A-Za-z0-9_\-]*)\s*"
    r"(?:[（(](?P<cn>[^）)]*)[)）])?\s*[:：]\s*(?P<range>.*?)\s*$"
)
# 区间连接符：- ~ — ～ 以及标准文档中常见的 en-dash（–, U+2013）与中文"至"。
_DASH = r"[-~—～–]|至"
_UPPER_LT_RE = re.compile(r"<\s*(\d+(?:\.\d+)?)(.*)$")      # 严格上限
_UPPER_LE_RE = re.compile(r"≤\s*(\d+(?:\.\d+)?)(.*)$")      # 含边界上限
_LOWER_GT_RE = re.compile(r">\s*(\d+(?:\.\d+)?)(.*)$")      # 严格下限
_LOWER_GE_RE = re.compile(r"≥\s*(\d+(?:\.\d+)?)(.*)$")      # 含边界下限
_RANGE_RE = re.compile(rf"(\d+(?:\.\d+)?)\s*(?:{_DASH})\s*(\d+(?:\.\d+)?)(.*)$")
# 标准文档中常见的修饰词/口语化前缀，解析边界数值前先剥离，不改变边界语义。
_FILLER_RE = re.compile(r"(约|常见为|常作正常参考|或)\s*")
# 按性别拆分的分段："男性约 9–50；女性约 7–40" → [("male", "约 9–50"), ("female", "约 7–40")]
_SEX_SEGMENT_RE = re.compile(r"(男性|女性)\s*([^；;]*)")


def _to_number(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _parse_bound(rng: str) -> dict | None:
    """解析剥离修饰词后的单段边界文本，返回边界字段 dict 或 None（解析失败）。"""
    rng = _FILLER_RE.sub("", rng).strip()
    if not rng:
        return None
    m_ult = _UPPER_LT_RE.match(rng)
    m_ule = _UPPER_LE_RE.match(rng)
    m_lgt = _LOWER_GT_RE.match(rng)
    m_lge = _LOWER_GE_RE.match(rng)
    m_r = _RANGE_RE.match(rng)
    if m_ult:
        return {"lower": None, "upper": _to_number(m_ult.group(1)),
                "lower_inclusive": True, "upper_inclusive": False,
                "unit": m_ult.group(2).strip()}
    if m_ule:
        return {"lower": None, "upper": _to_number(m_ule.group(1)),
                "lower_inclusive": True, "upper_inclusive": True,
                "unit": m_ule.group(2).strip()}
    if m_lgt:
        return {"lower": _to_number(m_lgt.group(1)), "upper": None,
                "lower_inclusive": False, "upper_inclusive": True,
                "unit": m_lgt.group(2).strip()}
    if m_lge:
        return {"lower": _to_number(m_lge.group(1)), "upper": None,
                "lower_inclusive": True, "upper_inclusive": True,
                "unit": m_lge.group(2).strip()}
    if m_r:
        return {"lower": _to_number(m_r.group(1)), "upper": _to_number(m_r.group(2)),
                "lower_inclusive": True, "upper_inclusive": True,
                "unit": m_r.group(3).strip()}
    return None


def _parse_range_text(range_text: str) -> list[dict]:
    """解析纯范围文本（不含指标名前缀），供表格解析路径直接调用。

    与 parse_reference_segment 共享性别分段 + 边界解析逻辑，但不经过
    _LINE_RE（后者要求指标名是单个不含空格的 token，无法承载
    "FDG-PET SUVR"、"CSF p-tau181" 这类含空格/连字符的复合指标名——
    表格场景下指标名已从单元格单独提取，不需要再从整行文本切分）。

    返回 [{unit, lower, upper, lower_inclusive, upper_inclusive, sex}]，
    不含 indicator_name/name_cn，由调用方补充。
    """
    rng = range_text.strip()
    if not rng:
        return []
    sex_segments = _SEX_SEGMENT_RE.findall(rng)
    if sex_segments:
        results = []
        sex_map = {"男性": "male", "女性": "female"}
        for label, seg_text in sex_segments:
            bound = _parse_bound(seg_text)
            if bound is None:
                continue
            results.append({**bound, "sex": sex_map[label]})
        return results
    bound = _parse_bound(rng)
    if bound is None or (bound["lower"] is None and bound["upper"] is None):
        return []
    return [{**bound, "sex": None}]


def parse_reference_segment(text: str) -> list[dict]:
    """确定性解析单行参考标准，返回 [{indicator_name, name_cn, unit, lower, upper,
    lower_inclusive, upper_inclusive, sex}]。

    支持 "<21 μmol/L"、"3.5-9.5 ×10⁹/L"、"≥140 mmHg"、"≤21 μmol/L"、
    "约 15–40"（en-dash + 修饰词）、"男性约 9–50；女性约 7–40"（性别分段）等格式。
    - 严格边界（<、>）→ 对应 inclusive=False；含边界（≤、≥）与区间 → inclusive=True。
    - 含"男性"/"女性"分段时，拆分为两条记录，sex 分别为 "male"/"female"；
      不含性别分段时 sex 为 None（通用范围）。
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

    sex_segments = _SEX_SEGMENT_RE.findall(rng)
    if sex_segments:
        results = []
        sex_map = {"男性": "male", "女性": "female"}
        for label, seg_text in sex_segments:
            bound = _parse_bound(seg_text)
            if bound is None:
                continue
            results.append({
                "indicator_name": name,
                "name_cn": cn,
                "unit": bound["unit"],
                "lower": bound["lower"],
                "upper": bound["upper"],
                "lower_inclusive": bound["lower_inclusive"],
                "upper_inclusive": bound["upper_inclusive"],
                "sex": sex_map[label],
            })
        return results

    bound = _parse_bound(rng)
    if bound is None or (bound["lower"] is None and bound["upper"] is None):
        return []
    return [{
        "indicator_name": name,
        "name_cn": cn,
        "unit": bound["unit"],
        "lower": bound["lower"],
        "upper": bound["upper"],
        "lower_inclusive": bound["lower_inclusive"],
        "upper_inclusive": bound["upper_inclusive"],
        "sex": None,
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
            "sex": None,
        })
    return valid


def _parse_tables_from_docx(file_path: str) -> list[dict]:
    """从 docx 文件的表格中提取参考范围（脂肪肝/AD 标准格式）。

    支持两种表格格式：
    1. 脂肪肝格式：指标名 | 正常范围 | 脂肪肝标准 | 单位
    2. AD 格式：指标名 | normal_or_control | ad_pattern | 其他列
       —— 仅提取 normal_or_control（正常/对照）列作为 ReferenceRange。
       ad_pattern 列多为方向性描述（如"显著降低"），并非与 normal_or_control
       对称的数值区间，若同样入库会与 normal_or_control 用同一 indicator_name
       产生互相冲突、排序不确定的两条记录（详见评审记录）。ad_pattern 目前
       只作为文档内容供 LLM 叙述引用，不参与预测时的范围匹配。

    返回 [{indicator_name, name_cn, unit, lower, upper, lower_inclusive,
           upper_inclusive, category, sex}, ...]
    """
    if not Path(file_path).exists():
        logger.warning(f"File not found for table parsing: {file_path}")
        return []

    try:
        docx_doc = DocxDocument(file_path)
    except Exception as e:
        logger.warning(f"Failed to open docx file {file_path}: {e}")
        return []

    items = []

    for table in docx_doc.tables:
        if len(table.rows) < 2:  # 至少需要标题行+数据行
            continue

        # 读取标题行判断格式
        header_cells = [cell.text.strip() for cell in table.rows[0].cells]

        # 判断是否为脂肪肝格式（包含"正常范围"/"脂肪肝标准"/"单位"）
        is_fatty_liver = any("正常范围" in h or "脂肪肝" in h for h in header_cells)

        # 判断是否为 AD 格式（包含"normal_or_control"/"ad_pattern"）
        is_ad = any("normal" in h.lower() or "ad_pattern" in h for h in header_cells)

        if not (is_fatty_liver or is_ad):
            continue  # 跳过不符合格式的表格

        # 解析数据行
        for row_idx, row in enumerate(table.rows[1:], start=2):  # 跳过标题行
            cells = [cell.text.strip() for cell in row.cells]

            if len(cells) < 2:
                continue

            indicator_raw = cells[0]  # 第一列：指标名（可能含中文）

            if not indicator_raw or indicator_raw in ("字段", "指标名", "indicator_name"):
                continue  # 跳过空行或重复标题行

            # 提取指标名和中文名。标准文档里的指标名不止单个 ASCII 词，
            # 常见 "FDG-PET SUVR（...)"、"CSF p-tau181（...)"、
            # "CSF Aβ42/Aβ40（...)" 这类含空格/斜杠/希腊字母的复合名——
            # 因此匹配"括号前的全部内容"而非局限于单个 [A-Za-z0-9_-] token，
            # 只要求以英文字母开头（用于和纯中文行区分）。
            match = re.match(r"^([A-Za-z][^（(]*?)\s*[（(]([^）)]+)[)）]?\s*$", indicator_raw)
            if match:
                indicator_name = match.group(1).strip()
                name_cn = match.group(2).strip()
            else:
                # 无中文括注：整行即指标名（仍要求以英文字母开头）
                if re.match(r"^[A-Za-z]", indicator_raw):
                    indicator_name = indicator_raw.strip()
                    name_cn = ""
                else:
                    continue  # 无法识别指标名（如纯中文表头行）

            # 根据格式提取范围
            if is_fatty_liver and len(cells) >= 4:
                # 脂肪肝格式：[指标名, 正常范围, 脂肪肝标准, 单位]
                # 这里只提取"正常范围"列（作为参考范围）；单位列独立于范围文本，
                # 不再拼接到一起解析（range_text 内本身有时也含单位/说明文字，
                # 拼接会重复，如 "5%" + "%" → "% %"）。
                range_text = cells[1]  # 正常范围列
                unit_col = cells[3] if len(cells) > 3 else ""

                parsed_ranges = _parse_range_text(range_text)
                if parsed_ranges:
                    for pr in parsed_ranges:
                        items.append({
                            "indicator_name": indicator_name,
                            "name_cn": name_cn,
                            "unit": pr["unit"] or unit_col,
                            "lower": pr["lower"],
                            "upper": pr["upper"],
                            "lower_inclusive": pr["lower_inclusive"],
                            "upper_inclusive": pr["upper_inclusive"],
                            "sex": pr["sex"],
                        })

            elif is_ad and len(cells) >= 3:
                # AD 格式：[指标名, normal_or_control, ad_pattern, ...]
                # 只解析 normal_or_control 列——它是预测时应作为"正常范围"参与
                # 异常判定的一侧；ad_pattern 多是方向性描述，不入库为 ReferenceRange。
                normal_text = cells[1]  # normal_or_control 列

                if normal_text and normal_text not in ("-", "—", "无", "N/A"):
                    parsed_ranges = _parse_range_text(normal_text)
                    if parsed_ranges:
                        for pr in parsed_ranges:
                            items.append({
                                "indicator_name": indicator_name,
                                "name_cn": name_cn,
                                "unit": pr["unit"],
                                "lower": pr["lower"],
                                "upper": pr["upper"],
                                "lower_inclusive": pr["lower_inclusive"],
                                "upper_inclusive": pr["upper_inclusive"],
                                "sex": pr["sex"],
                                "category": "AD-正常对照",
                            })

    logger.info(f"Parsed {len(items)} ranges from tables in {file_path}")
    return items


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

    # 优先从原始 docx 文件的表格中提取参考范围（支持脂肪肝/AD 标准格式）
    table_items: list[dict] = []
    if doc.file_path:
        try:
            table_items = _parse_tables_from_docx(doc.file_path)
            logger.info(f"Extracted {len(table_items)} items from tables in doc {document_id}")
        except Exception:
            logger.warning(f"Failed to parse tables from {doc.file_path}, fallback to chunk parsing", exc_info=True)

    # 注意：parser.py 把 docx 表格行也写入了 chunk 文本（格式 "| 单元格 |"）。
    # 这些行仍然喂给确定性/LLM 解析（不在这里过滤）——LLM 常常正是从这些
    # 表格行文本中提取出结构化范围的（尤其是表格解析器未覆盖的复杂单元格）。
    # 表格解析与段落解析（确定性+LLM）可能因此对同一范围各产出一次，
    # 重复由下方合并阶段按逻辑键去重解决，而不是在这里丢弃原始输入——
    # 早期尝试在此处按 "|" 前缀跳过表格行，会让 LLM 失去唯一的数据来源
    # （章节标题等纯叙述文本本身不含可提取范围），导致 LLM 合法返回空结果
    # 却被下方失败保护误判为"提取失败"而整体 abort。

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
    # ① 本应有 LLM 解析的片段（llm_fragments 非空）但 LLM 失败或产出为空 →
    #    整体 abort 并保留旧数据。LLM 返回空可能意味着输出非法 JSON 或无有效条目，
    #    无法证明空结果合法；若放行，参考范围会被静默缩小为部分结果，
    #    同步接口显示成功但后续预测/SSE/PDF 都基于不完整标准。
    if llm_fragments and (llm_failed or not llm_items):
        raise ValueError(
            "LLM 提取参考范围失败或未产出有效条目，已保留文档原有解析结果（不替换为部分数据），请检查后重试"
        )

    # 合并：表格解析优先（精确结构化），然后段落解析（确定性+LLM）
    merged = table_items + deterministic + llm_items

    # 同一指标常在文档不同段落重复出现（如正文叙述与附表各写一遍同一范围），
    # 表格解析与段落解析（确定性/LLM）也可能各命中一次同一行。按逻辑范围
    # （指标名+性别+边界值+单位+开闭区间）去重，保留先出现的一条
    # （表格解析优先于段落解析）。
    #
    # 注意：category 不参与去重键——它是描述性元数据（如章节标题），
    # LLM 路径常常填充它而表格/确定性路径留空，同一逻辑范围会因此产生
    # 不同的 category 取值，若把 category 计入键会让本应去重的重复行逃过去重。
    seen_keys: set[tuple] = set()
    items: list[dict] = []
    for it in merged:
        lower = it.get("lower")
        upper = it.get("upper")
        # lower_inclusive/upper_inclusive 只在对应边界非 None 时才有语义
        # （如 "<21" 的 lower 为 None，lower_inclusive 无意义）。不同解析
        # 路径在边界缺失时填的默认值不一致（True vs False），若原样计入
        # 去重键会把语义相同的一条范围误判成两条不同记录。
        key = (
            it["indicator_name"].strip().lower(),
            it.get("sex"),
            lower,
            upper,
            (it.get("unit") or "").strip(),
            bool(it.get("lower_inclusive", True)) if lower is not None else None,
            bool(it.get("upper_inclusive", True)) if upper is not None else None,
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        items.append(it)

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
