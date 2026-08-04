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


if __name__ == "__main__":
    unittest.main()
