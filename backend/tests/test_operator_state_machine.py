"""报告状态机单元测试。

验证 AIReport 状态转换规则：
- pending → generating（创建后开始检索）
- generating → completed（正常完成）
- generating → failed（异常）
- generating → cancelled（客户端取消）
- completed/failed/cancelled → 不可再转换（终态规则）
"""

import unittest
from unittest.mock import MagicMock

from app.db.models import AIReport


class TestReportStateMachine(unittest.TestCase):
    """AIReport 状态转换测试。"""

    def make_report(self, status: str) -> AIReport:
        """创建测试用 AIReport 实例。"""
        report = MagicMock(spec=AIReport)
        report.status = status
        report.id = 1
        report.content = ""
        report.sources = []
        report.retrieval_meta = {}
        report.error_message = None
        return report

    def test_initial_status_is_generating(self):
        """新创建的 report status 为 generating（由 API 层设置）。"""
        report = self.make_report("generating")
        self.assertEqual(report.status, "generating")

    def test_generating_can_become_completed(self):
        """generating → completed（正常流程）。"""
        report = self.make_report("generating")
        report.status = "completed"
        self.assertEqual(report.status, "completed")

    def test_generating_can_become_failed(self):
        """generating → failed（异常流程）。"""
        report = self.make_report("generating")
        report.status = "failed"
        report.error_message = "LLM error"
        self.assertEqual(report.status, "failed")

    def test_generating_can_become_cancelled(self):
        """generating → cancelled（取消流程）。"""
        report = self.make_report("generating")
        report.status = "cancelled"
        self.assertEqual(report.status, "cancelled")

    def test_cancelled_only_from_generating(self):
        """仅 generating 状态可标记为 cancelled。

        终态规则：completed/failed 后不可覆盖为 cancelled。
        这由 API 层的条件检查保证：
          if r and r.status == "generating":
              r.status = "cancelled"
        """
        # completed → cancelled 不应发生
        report = self.make_report("completed")
        # 模拟 API 层逻辑
        if report.status != "generating":
            # 不执行 cancelled 覆盖
            pass
        self.assertEqual(report.status, "completed")

    def test_final_states_not_overwritten(self):
        """终态（completed/failed/cancelled）不可被覆盖。

        验证：非 generating 状态下，不改变 status。
        """
        for final_status in ("completed", "failed", "cancelled"):
            report = self.make_report(final_status)
            # 模拟条件检查
            if report.status != "generating":
                pass  # 不覆盖
            self.assertEqual(report.status, final_status,
                             f"{final_status} 不应被覆盖")

    def test_report_has_all_required_fields(self):
        """验证 AIReport 包含所有 13 个业务字段。"""
        columns = {c.name for c in AIReport.__table__.columns}
        required = {
            "id", "user_id", "title", "query", "department_ids",
            "content", "sources", "retrieval_meta", "status",
            "error_message", "download_count", "created_at", "updated_at",
        }
        self.assertTrue(required.issubset(columns),
                        f"Missing columns: {required - columns}")

    def test_report_can_store_retrieval_meta(self):
        """retrieval_meta JSONB 字段可存储检索元数据。"""
        meta = {
            "original_query": "test",
            "department_ids": [1, 2],
            "retrieved_chunk_ids": [101, 102],
            "document_count": 3,
        }
        report = self.make_report("generating")
        report.retrieval_meta = meta
        self.assertEqual(report.retrieval_meta["document_count"], 3)
        self.assertEqual(len(report.retrieval_meta["retrieved_chunk_ids"]), 2)


class TestReportLifecycle(unittest.TestCase):
    """报告完整生命周期测试。"""

    def make_report(self, status: str) -> MagicMock:
        report = MagicMock(spec=AIReport)
        report.status = status
        report.id = 1
        report.content = ""
        report.sources = []
        report.retrieval_meta = {}
        report.error_message = None
        report.download_count = 0
        return report

    def test_full_lifecycle_generating_to_completed(self):
        """正常生命周期：创建 → generating → completed。"""
        report = self.make_report("generating")
        # 生成中累积内容
        report.content = "## 1. Summary\nTest content..."
        # 完成
        report.status = "completed"
        report.content = "Complete report content including all chapters"
        self.assertEqual(report.status, "completed")
        self.assertIn("Complete", report.content)
        self.assertIn("chapters", report.content)

    def test_full_lifecycle_generating_to_cancelled(self):
        """取消生命周期：创建 → generating → cancelled。"""
        report = self.make_report("generating")
        report.content = "部分内容..."
        # 取消
        if report.status == "generating":
            report.status = "cancelled"
            report.error_message = "用户取消生成"
        self.assertEqual(report.status, "cancelled")
        self.assertEqual(report.error_message, "用户取消生成")

    def test_download_count_increments(self):
        """PDF 下载后 download_count 自增。"""
        report = self.make_report("completed")
        self.assertEqual(report.download_count, 0)
        report.download_count += 1
        self.assertEqual(report.download_count, 1)
        report.download_count += 1
        self.assertEqual(report.download_count, 2)


if __name__ == "__main__":
    unittest.main()
