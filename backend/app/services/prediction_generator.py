"""AI 操作者预测报告生成服务。

由 operator.py 创建 AIReport(status=generating, analysis_type='predictive')
并传入 report_id；本服务负责：查病例统计、算概率、LLM 叙述、SSE 输出、
节流持久化。
"""
import asyncio
import json
import logging
import time as _time
from datetime import date, datetime, timezone
from typing import AsyncGenerator, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIReport, CaseRecord, Disease, ReferenceRange
from app.services.prediction_engine import (
    analyze_indicators,
    compute_composite_probability,
    select_representative_cases,
)

logger = logging.getLogger(__name__)

_PREDICTION_SYSTEM_PROMPT = """你是一位临床辅助分析助手。你的任务是：基于代码层计算出的统计数据，为一份患者指标预测报告撰写叙述性内容。

## 已确定的统计事实（必须原样采用，禁止改写或虚构）
- 综合匹配等级：{band}（区间 {probability_range}%）
- 若样本量不足 5，必须明确写"样本量不足，匹配度仅供参考"
- 各指标分析表（见上下文）

## 措辞限定（必须遵守）
band/probability_range 是**基于已录入病例的模式匹配参考**，不是临床发病概率。
任何提到等级或区间的句子必须伴随"基于已录入病例的模式匹配参考，非临床确诊概率"的限定，
禁止以绝对概率向用户陈述。

## 输出结构（Markdown）
## 1. 综合分析
（一句话给出综合匹配等级，引用统计事实，并带措辞限定）
## 2. 指标偏离分析
（逐项列出：实测值、参考范围、偏离度、在确诊人群中的异常率）
## 3. 支持证据
（引用检索到的确诊相似病例，说明哪些指标共同异常）
## 4. 局限性
（样本量、仅基于已录入病例、不构成诊断）
## 5. 结论与建议
（建议进一步检查项，结尾必须包含：本报告由 AI 基于知识库自动生成，仅供参考，不构成临床决策依据。）

## 原则
1. 不伪造任何数值；所有数字来自上下文统计。
2. 不给出确定性诊断；所有等级/区间表达必须伴随措辞限定。
3. 术语规范，逻辑清晰。"""

_PREDICTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _PREDICTION_SYSTEM_PROMPT),
    ("system", "患者主诉（如有）：{patient_summary}"),
    ("system", "指标分析结果：\n{indicator_table}"),
    ("system", "参考范围来源：\n{range_sources}"),
    ("system", "相似确诊病例：\n{case_sources}"),
    ("human", "请按上述结构生成预测分析报告。"),
])

_llm = ChatOpenAI(
    model=settings.DEEPSEEK_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True,
    temperature=0.2,
    max_tokens=2048,
    request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _range_map(ranges: list[ReferenceRange], patient_sex: str | None = None) -> dict[str, dict]:
    """ReferenceRange → analyze_indicators 需要的 ranges dict。

    必须透传 inclusive 字段——否则 analyze_indicators 读 `ref.get("lower_inclusive", True)`
    会默认按含边界处理，导致真实预测链路里 `<21` 退化成 `≤21`。

    选择契约：同一指标名可能存在多条（不同性别/文档/类别），输入须已按 created_at
    降序排列，同一 (指标名, 性别) 组合内**保留第一条（最新定义）**。

    性别解析规则（部分标准如脂肪肝 ALT 按男女分列）：
    - 若患者传了 patient_sex 且存在该性别的专属范围 → 使用该范围；
    - 否则若存在性别无关（sex=None）的通用范围 → 使用通用范围；
    - 否则（该指标只有性别专属范围，但未传 patient_sex，或只有异性范围）→
      该指标视为无可用范围，不写入结果（调用方据此报"缺少参考范围"）。

    键使用小写指标名，以支持大小写不敏感匹配；返回值额外携带 "_row"
    （原始 ReferenceRange 对象），供调用方构建来源引用时按已解析口径取用，
    避免来源展示与实际计算口径不一致。
    """
    by_key: dict[tuple[str, str | None], ReferenceRange] = {}
    for r in ranges:
        key = (r.indicator_name.strip().lower(), r.sex)
        if key in by_key:
            continue
        by_key[key] = r

    names = {k[0] for k in by_key}
    result: dict[str, dict] = {}
    for name in names:
        r = None
        if patient_sex and (name, patient_sex) in by_key:
            r = by_key[(name, patient_sex)]
        elif (name, None) in by_key:
            r = by_key[(name, None)]
        if r is None:
            continue
        result[name] = {
            "name": r.indicator_name,
            "unit": r.unit,
            "lower": r.lower,
            "upper": r.upper,
            "lower_inclusive": bool(r.lower_inclusive),
            "upper_inclusive": bool(r.upper_inclusive),
            "_row": r,
        }
    return result


def _format_range(
    lower: float | None,
    upper: float | None,
    lower_inclusive: bool = True,
    upper_inclusive: bool = True,
    unit: str = "",
) -> str:
    """按 inclusive 渲染参考范围边界符号，区分 < / ≤ / > / ≥ / 区间。"""
    u = f" {unit}".rstrip()
    if lower is None and upper is not None:
        return f"{'≤' if upper_inclusive else '<'}{upper}{u}"
    if upper is None and lower is not None:
        return f"{'≥' if lower_inclusive else '>'}{lower}{u}"
    return f"{lower}~{upper}{u}"


def _parse_visit_date(raw) -> "date | None":
    """尽力将 visit_date 解析为 date 用于排序；解析失败返回 None（视为最早）。

    纵向导入脚本统一写入 ISO 格式字符串（YYYY-MM-DD），但防御性处理
    非字符串/非法格式，避免与 "" 混合比较时抛 TypeError 或按字典序
    错误排序（如 "2020-2-01" 与 "2020-10-01"）。
    """
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw.strip():
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


def _sort_key(case: dict) -> tuple[int, "date", int]:
    """返回排序键：(是否有可解析日期, 日期, id)，降序比较取最新访视。

    无日期或日期非法时排最早（有日期的记录优先胜出），同分组内再按 id 兜底。
    """
    visit_date = _parse_visit_date((case.get("case_metadata") or {}).get("visit_date"))
    record_id = case.get("id") or 0
    if visit_date is None:
        return (0, date.min, record_id)
    return (1, visit_date, record_id)


def deduplicate_by_patient(cases: list[dict]) -> list[dict]:
    """按 (source_dataset, patient_label) 复合键去重：同患者只保留最新访视。

    - 只对纵向导入数据（case_metadata 含非空 source_dataset）去重；
    - 旧手工病例（metadata 为空或无 source_dataset）全部独立保留；
    - patient_label 为空/None/全空格时不参与去重，每条独立保留；
    - source_dataset/patient_label 统一 strip 后按原始大小写比较——
      两者均为程序生成的内部标识（非用户自由输入），不做大小写归一化，
      避免把恰好同名但不同大小写的独立数据集意外合并。

    排序：visit_date DESC > id DESC（二级排序，结果稳定）。
    """
    keyed: dict[tuple[str, str], dict] = {}  # (source_dataset, patient_label) -> case
    unlabeled: list[dict] = []

    for case in cases:
        label = (case.get("patient_label") or "").strip()
        source = ((case.get("case_metadata") or {}).get("source_dataset") or "").strip()

        if not label or not source:
            # 旧手工病例或无标签记录，独立保留
            unlabeled.append(case)
            continue

        key = (source, label)
        existing = keyed.get(key)
        if existing is None or _sort_key(case) > _sort_key(existing):
            keyed[key] = case

    return list(keyed.values()) + unlabeled


def _cases_to_dicts(cases: list[CaseRecord]) -> list[dict]:
    return [
        {
            "id": c.id,
            "disease_id": c.disease_id,
            "indicators": c.indicators or [],
            "patient_label": c.patient_label,
            "case_metadata": c.case_metadata or {}
        }
        for c in cases
    ]


def _build_sources(analyses: list[dict], representative_cases: list[dict], ranges: list[ReferenceRange]) -> list[dict]:
    """构建引用来源：参考范围条目 + 相似病例。"""
    sources: list[dict] = []
    idx = 1
    for r in ranges:
        # 来源内容按 inclusive 渲染边界符号，避免把 <21 表达成 ≤21/区间
        sources.append({
            "chunk_id": f"range-{r.id}",
            "document_id": r.document_id,
            "title": f"正常体征参考标准 · {r.name_cn or r.indicator_name}",
            "page_number": None,
            "citation_index": idx,
            "content": (
                f"{r.indicator_name} 参考范围: "
                f"{_format_range(r.lower, r.upper, bool(r.lower_inclusive), bool(r.upper_inclusive), r.unit or '')}"
            ),
            "images": [],
        })
        idx += 1
    for c in representative_cases:
        indicators_summary = "; ".join(
            f"{i.get('name')}={i.get('value')}{i.get('unit', '')}" for i in (c.get("indicators") or [])[:8]
        )
        sources.append({
            "chunk_id": f"case-{c['id']}",
            "document_id": None,
            "title": f"确诊病例 #{c['id']}",
            "page_number": None,
            "citation_index": idx,
            "content": indicators_summary,
            "images": [],
        })
        idx += 1
    return sources


async def generate_prediction(
    db: Session,
    user_id: int,
    report_id: int,
    disease_id: int,
    indicators: list[dict],
    patient_summary: Optional[str] = None,
    patient_sex: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """预测报告主入口。"""
    # 1. 校验疾病与范围
    disease = db.query(Disease).filter(Disease.id == disease_id).first()
    if not disease:
        _persist_failed(db, report_id, "", "疾病不存在")
        yield _sse("error", {"error": "疾病不存在"})
        return

    indicator_names = [i["name"] for i in indicators]
    # 大小写不敏感查询：用户可能输入 alt，数据库存储为 ALT
    indicator_names_lower = [name.strip().lower() for name in indicator_names]
    ranges = (
        db.query(ReferenceRange)
        .filter(func.lower(ReferenceRange.indicator_name).in_(indicator_names_lower))
        # 同一指标多条时取最新定义（created_at 降序，_range_map 保留首条）
        .order_by(ReferenceRange.created_at.desc())
        .all()
    )
    range_by_name = _range_map(ranges, patient_sex=patient_sex)
    missing = [n for n in indicator_names if n.strip().lower() not in range_by_name]
    if missing:
        _persist_failed(db, report_id, "", f"以下指标缺少参考范围: {missing}")
        yield _sse("error", {"error": f"缺少参考范围: {missing}"})
        return

    cases = (
        db.query(CaseRecord)
        .filter(CaseRecord.disease_id == disease_id, CaseRecord.confirmed.is_(True))
        .all()
    )
    cases_dict = _cases_to_dicts(cases)
    confirmed_cases = deduplicate_by_patient(cases_dict)
    total_cases = len(confirmed_cases)

    # 2. 代码层统计
    yield _sse("stage", {"stage": "analyzing", "message": "正在对照参考标准与病例库分析指标..."})
    analyses = analyze_indicators(indicators, range_by_name, confirmed_cases)
    probability = compute_composite_probability(analyses, total_cases)

    # 先落库统计结果：即使后续 LLM 流失败，prediction_result 也保留
    _persist_meta(db, report_id, prediction_result=probability, indicators=indicators)

    yield _sse("indicators", {"indicators": analyses, "probability": probability})
    yield _sse("stage", {"stage": "generating", "message": "正在生成预测报告..."})

    # 3. 选取代表性病例 + 构建来源
    # 报告/来源必须只展示与计算口径一致的范围——直接从 range_by_name 取回
    # _range_map 实际解析出的 ReferenceRange 行（已按小写指标名+性别解析），
    # 避免像之前那样重新按大小写敏感的 indicator_name 去重，与计算口径脱节。
    used_ranges: list[ReferenceRange] = [v["_row"] for v in range_by_name.values()]

    abnormal_names = {a["name"] for a in analyses if a["is_abnormal"]}
    representative = select_representative_cases(confirmed_cases, abnormal_names, top_n=5)
    sources = _build_sources(analyses, representative, used_ranges)

    indicator_table = "\n".join(
        f"- {a['name']}: 实测 {a['value']} {a['unit']}, "
        f"参考 {_format_range(a['lower'], a['upper'], a['lower_inclusive'], a['upper_inclusive'], a['unit'])}, "
        f"偏离 {a['deviation_pct']}%, 确诊异常率 {a['abnormal_rate_in_cases'] * 100:.1f}%"
        for a in analyses
    )
    range_sources = "\n".join(
        f"- {r.indicator_name}: {_format_range(r.lower, r.upper, bool(r.lower_inclusive), bool(r.upper_inclusive), r.unit or '')}（{r.name_cn or ''}）"
        for r in used_ranges
    )
    case_sources = "\n".join(
        f"- 病例#{c['id']}: " + "; ".join(f"{i.get('name')}={i.get('value')}{i.get('unit', '')}" for i in (c.get("indicators") or [])[:8])
        for c in representative
    ) or "- 无匹配相似病例"

    # 4. 流式生成
    full_content = ""
    last_persist = _time.monotonic()
    PERSIST_INTERVAL = 30
    try:
        async for chunk in _llm.astream(_PREDICTION_PROMPT.format_prompt(
            patient_summary=patient_summary or "无",
            indicator_table=indicator_table,
            range_sources=range_sources,
            case_sources=case_sources,
            band=probability["band"],
            probability_range=probability["probability_range"],
        ).to_messages()):
            content = chunk.content if hasattr(chunk, "content") else ""
            if content:
                full_content += content
                yield _sse("delta", {"content": content})
                now = _time.monotonic()
                if (now - last_persist) >= PERSIST_INTERVAL:
                    _persist_content(db, report_id, full_content)
                    last_persist = now
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Prediction stream failed for report %s", report_id)
        _persist_failed(db, report_id, full_content, str(exc))
        yield _sse("error", {"error": "报告生成过程中发生错误"})
        return

    # 5. 完成
    title = disease.name + " 指标预测分析"
    _persist_completed(db, report_id, full_content, sources, probability, indicators, title)
    yield _sse("sources", {"sources": sources})
    yield _sse("done", {"report_id": report_id})


def _persist_meta(db: Session, report_id: int, prediction_result: dict, indicators: list[dict]) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report:
        report.prediction_result = prediction_result
        report.indicators = indicators
        db.commit()


def _persist_content(db: Session, report_id: int, content: str) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report:
        report.content = content
        db.commit()


def _persist_completed(db, report_id, content, sources, prediction_result, indicators, title) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report and report.status == "generating":
        report.content = content
        report.sources = sources
        report.prediction_result = prediction_result
        report.indicators = indicators
        report.analysis_type = "predictive"
        report.title = title
        report.status = "completed"
        db.commit()


def _persist_failed(db, report_id, partial_content, error) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report and report.status == "generating":
        if partial_content:
            report.content = partial_content
        report.status = "failed"
        report.error_message = error
        db.commit()
