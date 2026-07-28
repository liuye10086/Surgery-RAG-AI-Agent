"""report_generator 服务单元测试。"""

import unittest
from unittest.mock import MagicMock, patch

from app.db.models import Department


class TestValidateDepartmentIds(unittest.TestCase):
    """_validate_department_ids 校验测试。"""

    def setUp(self):
        from app.services.report_generator import _validate_department_ids
        self.func = _validate_department_ids

    def test_none_input_returns_none(self):
        """None 输入 → 返回 None（全库检索）。"""
        db = MagicMock()
        result = self.func(db, None)
        self.assertIsNone(result)

    def test_empty_list_returns_none(self):
        """空列表 → 返回 None。"""
        db = MagicMock()
        result = self.func(db, [])
        self.assertIsNone(result)

    def test_valid_ids_returned(self):
        """全部有效的 ID → 原样返回。"""
        db = MagicMock()
        dept1 = MagicMock(spec=Department)
        dept1.id = 1
        dept2 = MagicMock(spec=Department)
        dept2.id = 2
        db.query.return_value.filter.return_value.all.return_value = [dept1, dept2]

        result = self.func(db, [1, 2])
        self.assertEqual(result, [1, 2])

    def test_invalid_id_raises_value_error(self):
        """存在无效 ID → 抛出 ValueError。"""
        db = MagicMock()
        dept1 = MagicMock(spec=Department)
        dept1.id = 1
        db.query.return_value.filter.return_value.all.return_value = [dept1]

        with self.assertRaises(ValueError) as ctx:
            self.func(db, [1, 99])
        self.assertIn("99", str(ctx.exception))

    def test_all_invalid_raises_value_error(self):
        """全部无效 ID → 抛出 ValueError。"""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with self.assertRaises(ValueError):
            self.func(db, [99, 100])


class TestRetrieveForReport(unittest.TestCase):
    """_retrieve_for_report 多科室检索合并测试。"""

    def setUp(self):
        from app.services.report_generator import _retrieve_for_report
        self.func = _retrieve_for_report

    @staticmethod
    def _make_retrieved_chunk(cid: int, score: float):
        """创建可用的模拟 RetrievedChunk。"""
        from app.rag.pipeline import RetrievedChunk

        rc = MagicMock(spec=RetrievedChunk)
        rc.chunk = MagicMock()
        rc.chunk.id = cid
        rc.score = score
        return rc

    @patch("app.services.report_generator.hybrid_search")
    def test_no_department_ids_calls_hybrid_search_none(self, mock_hs):
        """无科室 → hybrid_search(top_k=20, department_id=None)。"""
        mock_hs.return_value = []
        db = MagicMock()
        result = self.func(db, "test query", None)
        mock_hs.assert_called_once_with(db, "test query", top_k=20, department_id=None)
        self.assertEqual(result, [])

    @patch("app.services.report_generator.hybrid_search")
    def test_single_department_calls_hybrid_search_with_id(self, mock_hs):
        """单科室 → hybrid_search(top_k=20, department_id=n)。"""
        mock_hs.return_value = []
        db = MagicMock()
        result = self.func(db, "test query", [5])
        mock_hs.assert_called_once_with(db, "test query", top_k=20, department_id=5)
        self.assertEqual(result, [])

    @patch("app.services.report_generator.hybrid_search")
    def test_multi_department_merges_and_dedups(self, mock_hs):
        """多科室 → 去重 + RRF 排序 + 截断 top 20。"""
        chunk_a1 = self._make_retrieved_chunk(1, 0.8)
        chunk_a2 = self._make_retrieved_chunk(2, 0.6)
        chunk_b1 = self._make_retrieved_chunk(1, 0.9)  # 与 A 重复，更高分
        chunk_b2 = self._make_retrieved_chunk(3, 0.5)

        mock_hs.side_effect = [
            [chunk_a1, chunk_a2],
            [chunk_b1, chunk_b2],
        ]

        db = MagicMock()
        result = self.func(db, "test query", [1, 2])

        chunk_ids = [rc.chunk.id for rc in result]
        self.assertEqual(chunk_ids, [1, 2, 3])
        chunk1 = next(rc for rc in result if rc.chunk.id == 1)
        self.assertEqual(chunk1.score, 0.9)

    @patch("app.services.report_generator.hybrid_search")
    def test_truncates_to_20(self, mock_hs):
        """多科室结果超过 20 条时截断。"""
        chunks = [self._make_retrieved_chunk(i, 100 - i) for i in range(1, 31)]
        mock_hs.side_effect = [chunks[:15], chunks[15:]]

        db = MagicMock()
        result = self.func(db, "test query", [1, 2])

        self.assertLessEqual(len(result), 20)


class TestFormatDocs(unittest.TestCase):
    """_format_docs 测试。"""

    def test_formats_with_index_numbers(self):
        from app.services.report_generator import _format_docs

        rc1 = MagicMock()
        rc1.chunk = MagicMock()
        rc1.chunk.content = "内容A"
        rc2 = MagicMock()
        rc2.chunk = MagicMock()
        rc2.chunk.content = "内容B"

        result = _format_docs([rc1, rc2])
        self.assertIn("[1] 内容A", result)
        self.assertIn("[2] 内容B", result)


class TestSseFormatting(unittest.TestCase):
    """SSE 格式化测试。"""

    def test_sse_format(self):
        from app.services.report_generator import _sse

        result = _sse("delta", {"content": "hello"})
        self.assertIn("event: delta", result)
        self.assertIn("data: ", result)
        self.assertIn("hello", result)
        self.assertTrue(result.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
