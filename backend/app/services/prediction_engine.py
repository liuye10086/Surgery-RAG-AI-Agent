"""AI 操作者预测引擎：指标异常分析 + 综合匹配度/风险等级。

纯函数模块，不依赖 LLM 与 DB，便于离线单测。

注意措辞约定：输出的 band/probability_range 是"基于已录入病例的模式匹配参考"，
不是临床发病概率（见 Global Constraints「概率措辞约定」）。
"""
from typing import Optional


def classify_indicator(
    value: float,
    lower: Optional[float],
    upper: Optional[float],
    lower_inclusive: bool = True,
    upper_inclusive: bool = True,
) -> tuple[bool, float]:
    """判断指标是否超出参考范围。

    边界开闭语义（对应 reference_ranges 的 inclusive 字段）：
    - inclusive=True（≤ / ≥ / 区间）：边界值判为正常（value == upper 不异常）
    - inclusive=False（严格 < / >）：边界值判为异常（value == upper 异常）

    Returns:
        (is_abnormal, deviation_pct): deviation_pct 为相对边界的偏离百分比，
        正常时为 0.0。
    """
    if upper is not None:
        if value > upper or (not upper_inclusive and value == upper):
            pct = (value - upper) / upper * 100 if upper else 0.0
            return True, round(pct, 1)
    if lower is not None:
        if value < lower or (not lower_inclusive and value == lower):
            pct = (lower - value) / lower * 100 if lower else 0.0
            return True, round(pct, 1)
    return False, 0.0


def analyze_indicators(
    patient_indicators: list[dict],
    ranges: dict[str, dict],
    confirmed_cases: list[dict],
) -> list[dict]:
    """对每个患者指标做异常判定 + 病例异常率统计。

    Args:
        patient_indicators: [{"name","value","unit"}, ...]
        ranges: {indicator_name: {"name","unit","lower","upper"}}
        confirmed_cases: [{"indicators": [{"name","value","unit"}]}, ...]

    Returns:
        按 risk_weight 降序的指标分析列表，每项：
        {name, value, unit, lower, upper, lower_inclusive, upper_inclusive,
         is_abnormal, deviation_pct, present_rate_in_cases,
         abnormal_rate_in_cases, risk_weight}
    """
    results: list[dict] = []
    for ind in patient_indicators:
        ref = ranges.get(ind["name"])
        if not ref:
            continue
        lower = ref.get("lower")
        upper = ref.get("upper")
        lower_inclusive = ref.get("lower_inclusive", True)
        upper_inclusive = ref.get("upper_inclusive", True)
        value = ind["value"]
        is_abnormal, deviation_pct = classify_indicator(
            value, lower, upper, lower_inclusive, upper_inclusive,
        )

        present_count = 0
        abnormal_count = 0
        for case in confirmed_cases:
            matched = None
            for ci in case.get("indicators") or []:
                if ci.get("name") == ind["name"]:
                    matched = ci
                    break
            if matched is None:
                continue
            present_count += 1
            c_abnormal, _ = classify_indicator(
                matched["value"], lower, upper, lower_inclusive, upper_inclusive,
            )
            if c_abnormal:
                abnormal_count += 1

        total_cases = len(confirmed_cases) or 1
        present_rate = present_count / total_cases
        abnormal_rate = abnormal_count / total_cases if present_count else 0.0

        results.append({
            "name": ind["name"],
            "value": value,
            "unit": ind.get("unit") or ref.get("unit") or "",
            "lower": lower,
            "upper": upper,
            # 携带 inclusive，供报告/来源/前端把 <21 与 ≤21 正确区分渲染
            "lower_inclusive": bool(ref.get("lower_inclusive", True)),
            "upper_inclusive": bool(ref.get("upper_inclusive", True)),
            "is_abnormal": is_abnormal,
            "deviation_pct": deviation_pct,
            "present_rate_in_cases": round(present_rate, 4),
            "abnormal_rate_in_cases": round(abnormal_rate, 4),
            "risk_weight": round(abnormal_rate if is_abnormal else 0.0, 4),
        })

    results.sort(key=lambda x: x["risk_weight"], reverse=True)
    return results


_BANDS = [
    (0.8, "极高", [80, 95]),
    (0.6, "高", [60, 80]),
    (0.4, "中等", [40, 60]),
    (0.2, "低", [20, 40]),
    (0.0, "极低", [0, 20]),
]

_BAND_ORDER = {"极低": 0, "低": 1, "中等": 2, "高": 3, "极高": 4}


def compute_composite_probability(analyses: list[dict], total_cases: int) -> dict:
    """由指标分析结果计算综合匹配度/风险等级（模式匹配参考，非确诊概率）。

    公式：score = mean(risk_weight for abnormal indicators)。
    risk_weight = 该指标在确诊病例中的异常率（仅患者该指标异常时计）。

    Returns:
        {score, band, probability_range, abnormal_count, sample_size,
         insufficient_sample}
    """
    abnormal = [a for a in analyses if a.get("is_abnormal")]
    if not abnormal:
        return {
            "score": 0.0, "band": "极低", "probability_range": [0, 20],
            "abnormal_count": 0, "sample_size": total_cases,
            "insufficient_sample": total_cases < 5,
        }

    score = sum(a["risk_weight"] for a in abnormal) / len(abnormal)
    score = min(max(score, 0.0), 1.0)

    insufficient = total_cases < 5
    band = "极低"
    prob_range = [0, 20]
    for threshold, label, prange in _BANDS:
        if score >= threshold:
            band = label
            prob_range = prange
            break
    if insufficient and _BAND_ORDER[band] > _BAND_ORDER["中等"]:
        # 样本不足且得分高于"中等"时，降档并固定为 [20, 60]。
        # 不能沿用原 prob_range 再裁剪——否则 [80,95] 会变成 [80,60]，
        # 出现下界大于上界的非法区间。
        band = "中等"
        prob_range = [20, 60]

    return {
        "score": round(score, 3),
        "band": band,
        "probability_range": prob_range,
        "abnormal_count": len(abnormal),
        "sample_size": total_cases,
        "insufficient_sample": insufficient,
    }


def select_representative_cases(
    confirmed_cases: list[dict],
    abnormal_indicator_names: set[str],
    top_n: int = 5,
) -> list[dict]:
    """选取与患者异常指标重叠最多的确诊病例，作为报告引用来源。"""
    def overlap(case):
        names = {ci.get("name") for ci in case.get("indicators") or []}
        return len(names & abnormal_indicator_names)

    ranked = sorted(confirmed_cases, key=overlap, reverse=True)
    return [c for c in ranked[:top_n] if overlap(c) > 0]
