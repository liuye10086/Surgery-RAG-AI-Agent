"""预测引擎核心算法测试。"""
import unittest
from app.services.prediction_engine import (
    classify_indicator,
    analyze_indicators,
    compute_composite_probability,
    select_representative_cases,
)


def _range(name, lower=None, upper=None, unit="U/L"):
    return {"name": name, "unit": unit, "lower": lower, "upper": upper}


class ClassifyIndicatorTests(unittest.TestCase):
    def test_above_upper_is_abnormal(self):
        abnormal, pct = classify_indicator(35.0, None, 21.0)
        self.assertTrue(abnormal)
        self.assertAlmostEqual(pct, 66.7, places=1)  # (35-21)/21*100

    def test_below_lower_is_abnormal(self):
        abnormal, pct = classify_indicator(0.5, 1.0, None)
        self.assertTrue(abnormal)
        self.assertAlmostEqual(pct, 50.0, places=1)  # (1-0.5)/1*100

    def test_within_range_is_normal(self):
        abnormal, pct = classify_indicator(3.0, 1.0, 5.0)
        self.assertFalse(abnormal)
        self.assertEqual(pct, 0.0)

    def test_inclusive_upper_boundary_is_normal(self):
        # ≤21 时 value==21 判为正常
        abnormal, pct = classify_indicator(21.0, None, 21.0, upper_inclusive=True)
        self.assertFalse(abnormal)

    def test_exclusive_upper_boundary_is_abnormal(self):
        # <21 时 value==21 判为异常（严格上限）
        abnormal, pct = classify_indicator(21.0, None, 21.0, upper_inclusive=False)
        self.assertTrue(abnormal)
        self.assertEqual(pct, 0.0)

    def test_exclusive_lower_boundary_is_abnormal(self):
        # >140 时 value==140 判为异常（严格下限）
        abnormal, _ = classify_indicator(140.0, 140.0, None, lower_inclusive=False)
        self.assertTrue(abnormal)

    def test_no_bounds_is_normal(self):
        abnormal, pct = classify_indicator(10.0, None, None)
        self.assertFalse(abnormal)


class AnalyzeIndicatorsTests(unittest.TestCase):
    def test_matches_abnormality_rate_from_cases(self):
        patient = [{"name": "TBIL", "value": 35.0, "unit": "μmol/L"}]
        # ranges 的键约定为小写指标名（见 prediction_generator._range_map）
        ranges = {"tbil": _range("TBIL", upper=21.0, unit="μmol/L")}
        cases = [
            {"indicators": [{"name": "TBIL", "value": 38.0, "unit": "μmol/L"}]},
            {"indicators": [{"name": "TBIL", "value": 25.0, "unit": "μmol/L"}]},
            {"indicators": [{"name": "TBIL", "value": 12.0, "unit": "μmol/L"}]},
        ]
        analyses = analyze_indicators(patient, ranges, cases)
        self.assertEqual(len(analyses), 1)
        a = analyses[0]
        self.assertTrue(a["is_abnormal"])
        self.assertAlmostEqual(a["abnormal_rate_in_cases"], 2 / 3, places=3)
        self.assertAlmostEqual(a["risk_weight"], 2 / 3, places=3)

    def test_indicator_without_range_is_skipped(self):
        patient = [{"name": "UNKNOWN", "value": 5.0, "unit": "x"}]
        analyses = analyze_indicators(patient, {}, [])
        self.assertEqual(analyses, [])

    def test_patient_input_case_differs_from_range_key_still_matches(self):
        # 患者输入 ALT（大写），ranges 字典键为小写 alt（_range_map 的真实契约）
        patient = [{"name": "ALT", "value": 60.0, "unit": "U/L"}]
        ranges = {"alt": _range("ALT", upper=40.0, unit="U/L")}
        analyses = analyze_indicators(patient, ranges, [])
        self.assertEqual(len(analyses), 1)
        self.assertTrue(analyses[0]["is_abnormal"])

    def test_case_indicator_name_case_differs_from_patient_input(self):
        # 病例存的指标名大小写与患者输入不同（alt vs ALT），异常率统计仍应匹配
        patient = [{"name": "ALT", "value": 60.0, "unit": "U/L"}]
        ranges = {"alt": _range("ALT", upper=40.0, unit="U/L")}
        cases = [
            {"indicators": [{"name": "alt", "value": 55.0, "unit": "U/L"}]},
            {"indicators": [{"name": "alt", "value": 20.0, "unit": "U/L"}]},
        ]
        analyses = analyze_indicators(patient, ranges, cases)
        self.assertEqual(analyses[0]["present_rate_in_cases"], 1.0)
        self.assertEqual(analyses[0]["abnormal_rate_in_cases"], 0.5)


class CompositeProbabilityTests(unittest.TestCase):
    def test_no_abnormal_indicators(self):
        analyses = [{"is_abnormal": False, "risk_weight": 0.0}]
        result = compute_composite_probability(analyses, total_cases=50)
        self.assertEqual(result["band"], "极低")

    def test_all_abnormal_high_rates(self):
        analyses = [
            {"is_abnormal": True, "risk_weight": 0.7},
            {"is_abnormal": True, "risk_weight": 0.6},
        ]
        result = compute_composite_probability(analyses, total_cases=50)
        self.assertEqual(result["band"], "高")  # score=0.65 ∈ [0.6, 0.8)
        self.assertAlmostEqual(result["score"], 0.65)

    def test_small_sample_degrades_band(self):
        analyses = [{"is_abnormal": True, "risk_weight": 0.9}]
        result = compute_composite_probability(analyses, total_cases=3)
        self.assertTrue(result["insufficient_sample"])
        self.assertEqual(result["band"], "中等")  # 样本不足时封顶
        # 区间必须合法且单调：不得出现 [80, 60] 这类下界大于上界
        low, high = result["probability_range"]
        self.assertLessEqual(low, high)
        self.assertEqual([low, high], [20, 60])


class RepresentativeCaseTests(unittest.TestCase):
    def test_ranks_by_overlap(self):
        cases = [
            {"id": 1, "indicators": [{"name": "TBIL", "value": 38.0}]},
            {"id": 2, "indicators": [{"name": "TBIL", "value": 12.0}, {"name": "ALT", "value": 30.0}]},
        ]
        selected = select_representative_cases(cases, {"TBIL"}, top_n=1)
        self.assertEqual(selected[0]["id"], 1)

    def test_overlap_matching_is_case_insensitive(self):
        # abnormal_indicator_names 大写，病例指标名小写，仍应命中重叠
        cases = [
            {"id": 1, "indicators": [{"name": "tbil", "value": 38.0}]},
            {"id": 2, "indicators": [{"name": "alt", "value": 30.0}]},
        ]
        selected = select_representative_cases(cases, {"TBIL"}, top_n=5)
        self.assertEqual([c["id"] for c in selected], [1])


if __name__ == "__main__":
    unittest.main()
