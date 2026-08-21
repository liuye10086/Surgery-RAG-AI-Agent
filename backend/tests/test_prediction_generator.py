"""预测生成器持久化守卫测试。"""
import unittest
from unittest.mock import MagicMock
from app.services.prediction_generator import _persist_completed, _persist_failed, _persist_meta


class PredictionPersistTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.report = MagicMock()
        self.report.id = 1
        self.report.status = "generating"
        self.db.query.return_value.filter.return_value.first.return_value = self.report

    def test_completed_allows_generating(self):
        # 签名：_persist_completed(db, report_id, content, sources,
        #       prediction_result, indicators, title)
        # 注意：prediction_result 是含 band/score 的 dict，indicators 是 list。
        # 断言 report.prediction_result["band"] 必须能在传入的 dict 上取到。
        _persist_completed(self.db, 1, "内容", [],
                           {"score": 0.8, "band": "高"}, [],
                           "胆囊结石 指标预测分析")
        self.assertEqual(self.report.status, "completed")
        self.assertEqual(self.report.analysis_type, "predictive")
        self.assertEqual(self.report.prediction_result["band"], "高")
        self.assertEqual(self.report.indicators, [])
        self.db.commit.assert_called_once()

    def test_completed_skips_non_generating(self):
        self.report.status = "completed"
        # 参数与实现签名完全对齐：prediction_result={}，indicators=[]（list）
        _persist_completed(self.db, 1, "新", [], {}, [], "标题")
        self.db.commit.assert_not_called()

    def test_failed_allows_generating(self):
        _persist_failed(self.db, 1, "部分", "LLM 错误")
        self.assertEqual(self.report.status, "failed")
        self.assertEqual(self.report.error_message, "LLM 错误")

    def test_meta_writes_prediction_result(self):
        _persist_meta(self.db, 1, prediction_result={"band": "高", "score": 0.85}, indicators=[{"name": "TBIL", "value": 35}])
        self.assertEqual(self.report.prediction_result["band"], "高")
        self.assertEqual(self.report.indicators[0]["name"], "TBIL")


class RangeMapSexResolutionTests(unittest.TestCase):
    """_range_map 的性别分列范围解析：脂肪肝 ALT 等按男女分列的标准。"""

    def _row(self, name, sex=None, lower=None, upper=None):
        from app.services.prediction_generator import ReferenceRange
        row = MagicMock(spec=ReferenceRange)
        row.indicator_name = name
        row.sex = sex
        row.lower = lower
        row.upper = upper
        row.lower_inclusive = True
        row.upper_inclusive = True
        row.unit = "U/L"
        return row

    def test_uses_matching_sex_specific_range_when_patient_sex_given(self):
        from app.services.prediction_generator import _range_map
        rows = [self._row("ALT", sex="male", lower=9, upper=50),
                self._row("ALT", sex="female", lower=7, upper=40)]
        result = _range_map(rows, patient_sex="female")
        self.assertEqual(result["alt"]["lower"], 7)
        self.assertEqual(result["alt"]["upper"], 40)

    def test_falls_back_to_generic_range_when_no_sex_specific_entry(self):
        from app.services.prediction_generator import _range_map
        rows = [self._row("AST", sex=None, lower=15, upper=40)]
        result = _range_map(rows, patient_sex="male")
        self.assertEqual(result["ast"]["lower"], 15)

    def test_sex_only_indicator_without_patient_sex_yields_no_range(self):
        # 只有性别专属范围，未传 patient_sex → 该指标不应出现在结果中
        from app.services.prediction_generator import _range_map
        rows = [self._row("ALT", sex="male", lower=9, upper=50),
                self._row("ALT", sex="female", lower=7, upper=40)]
        result = _range_map(rows, patient_sex=None)
        self.assertNotIn("alt", result)

    def test_generic_range_used_when_patient_sex_given_but_no_match(self):
        from app.services.prediction_generator import _range_map
        rows = [self._row("TBIL", sex=None, lower=None, upper=17.1)]
        result = _range_map(rows, patient_sex="male")
        self.assertEqual(result["tbil"]["upper"], 17.1)


class SortKeyDateParsingTests(unittest.TestCase):
    """_sort_key 对非规范 visit_date 的健壮性。"""

    def test_iso_date_string_sorts_correctly_across_months(self):
        from app.services.prediction_generator import _sort_key
        early = {"id": 1, "case_metadata": {"visit_date": "2020-02-01"}}
        late = {"id": 2, "case_metadata": {"visit_date": "2020-10-01"}}
        # 字典序会误判 "2020-10-01" < "2020-2-01"（若未补零），
        # 但纵向导入脚本始终写 ISO 补零格式，这里验证真实 date 比较正确。
        self.assertLess(_sort_key(early), _sort_key(late))

    def test_malformed_date_string_does_not_raise_and_sorts_as_earliest(self):
        from app.services.prediction_generator import _sort_key
        malformed = {"id": 1, "case_metadata": {"visit_date": "not-a-date"}}
        valid = {"id": 2, "case_metadata": {"visit_date": "2020-01-01"}}
        self.assertLess(_sort_key(malformed), _sort_key(valid))

    def test_missing_visit_date_does_not_raise(self):
        from app.services.prediction_generator import _sort_key
        case = {"id": 1, "case_metadata": {}}
        # 不应抛异常；有日期的记录应排在其后面
        key = _sort_key(case)
        with_date = {"id": 2, "case_metadata": {"visit_date": "2020-01-01"}}
        self.assertLess(key, _sort_key(with_date))


class TestDeduplicateByPatient(unittest.TestCase):

    def test_deduplicate_keeps_latest_visit_per_patient_within_same_dataset(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},
            {"id": 3, "patient_label": "P002", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-03-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
        p001 = next(c for c in result if c["patient_label"] == "P001")
        self.assertEqual(p001["case_metadata"]["visit_date"], "2020-06-01")
        self.assertEqual(p001["id"], 2)

    def test_deduplicate_keeps_same_label_from_different_datasets_separately(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)

    def test_deduplicate_keeps_same_label_from_two_nonblank_sources_separately(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "dataset_a", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "dataset_b", "visit_date": "2020-06-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
        sources = {c["case_metadata"]["source_dataset"] for c in result}
        self.assertEqual(sources, {"dataset_a", "dataset_b"})

    def test_deduplicate_uses_id_when_visit_date_missing_or_tied(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 3, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 4, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
        p001 = next(c for c in result if c["patient_label"] == "P001")
        self.assertEqual(p001["id"], 2)
        p002 = next(c for c in result if c["patient_label"] == "P002")
        self.assertEqual(p002["id"], 4)

    def test_deduplicate_all_dates_missing_uses_max_id(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
            {"id": 3, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 3)

    def test_deduplicate_keeps_unlabeled_cases_independently(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": None, "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 2, "patient_label": "", "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 3, "patient_label": "   ", "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 4, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 4)

    def test_deduplicate_keeps_old_manual_cases_even_with_duplicate_labels(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": None, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)

    def test_deduplicate_handles_input_order_reversal(self):
        from app.services.prediction_generator import deduplicate_by_patient
        forward = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},
        ]
        backward = list(reversed(forward))
        self.assertEqual(
            deduplicate_by_patient(forward)[0]["id"],
            deduplicate_by_patient(backward)[0]["id"]
        )

    def test_deduplicate_mixed_scenario_all_types(self):
        from app.services.prediction_generator import deduplicate_by_patient
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},
            {"id": 3, "patient_label": "P001", "case_metadata": {}, "indicators": []},
            {"id": 4, "patient_label": None, "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 5, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2021-01-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 4)
        ids = {c["id"] for c in result}
        self.assertEqual(ids, {2, 3, 4, 5})

    def test_cases_to_dicts_includes_dedup_fields(self):
        from app.services.prediction_generator import _cases_to_dicts
        case = MagicMock(
            id=1,
            disease_id=1,
            indicators=[{"name": "alt", "value": 60}],
            patient_label="P001",
            case_metadata={"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}
        )
        result = _cases_to_dicts([case])
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[0]["patient_label"], "P001")
        self.assertEqual(result[0]["case_metadata"]["source_dataset"], "longitudinal_300")
        self.assertEqual(result[0]["case_metadata"]["visit_date"], "2020-01-01")
        self.assertEqual(result[0]["indicators"], [{"name": "alt", "value": 60}])

    def test_cases_to_dicts_preserves_empty_indicators_normalization(self):
        from app.services.prediction_generator import _cases_to_dicts
        case_with_none = MagicMock(
            id=1, disease_id=1, indicators=None,
            patient_label="P001", case_metadata={}
        )
        result = _cases_to_dicts([case_with_none])
        self.assertEqual(result[0]["indicators"], [])


if __name__ == "__main__":
    unittest.main()
