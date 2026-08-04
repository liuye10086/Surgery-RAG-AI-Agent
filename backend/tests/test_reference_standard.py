"""参考标准解析服务测试。"""
import unittest
from unittest.mock import MagicMock, patch
from app.services.reference_standard import (
    parse_reference_segment,
    _extract_json_array,
    sync_reference_ranges,
)


class ReferenceParsingTests(unittest.TestCase):
    def test_parse_lt_form(self):
        # 严格上限：<21 → upper=21, upper_inclusive=False
        self.assertEqual(
            parse_reference_segment("TBIL（总胆红素）：<21 μmol/L"),
            [{"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": False}],
        )

    def test_parse_range_form(self):
        # 区间 → 两端 inclusive=True
        self.assertEqual(
            parse_reference_segment("WBC（白细胞计数）：3.5-9.5 ×10⁹/L"),
            [{"indicator_name": "WBC", "name_cn": "白细胞计数", "unit": "×10⁹/L",
              "lower": 3.5, "upper": 9.5, "lower_inclusive": True, "upper_inclusive": True}],
        )

    def test_parse_le_form_inclusive_upper(self):
        # ≤21 → upper_inclusive=True（与 <21 的 upper_inclusive=False 区分）
        self.assertEqual(
            parse_reference_segment("ALP（碱性磷酸酶）：≤21 μmol/L"),
            [{"indicator_name": "ALP", "name_cn": "碱性磷酸酶", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": True}],
        )

    def test_parse_gt_form_exclusive_lower(self):
        # 严格下限：>140 → lower=140, lower_inclusive=False
        self.assertEqual(
            parse_reference_segment("SBP（收缩压）：>140 mmHg"),
            [{"indicator_name": "SBP", "name_cn": "收缩压", "unit": "mmHg",
              "lower": 140.0, "upper": None, "lower_inclusive": False, "upper_inclusive": True}],
        )

    def test_parse_ge_form_inclusive_lower(self):
        # 含边界下限：≥140 → lower=140, lower_inclusive=True
        self.assertEqual(
            parse_reference_segment("SBP（收缩压）：≥140 mmHg"),
            [{"indicator_name": "SBP", "name_cn": "收缩压", "unit": "mmHg",
              "lower": 140.0, "upper": None, "lower_inclusive": True, "upper_inclusive": True}],
        )

    def test_parse_list_prefix_line(self):
        # 列表前缀行也应被确定性解析命中（- TBIL...）
        self.assertEqual(
            parse_reference_segment("- TBIL（总胆红素）：<21 μmol/L"),
            [{"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": False}],
        )

    def test_parse_unparseable_returns_empty(self):
        self.assertEqual(parse_reference_segment("参考标准为临床公认值"), [])

    def test_extract_json_array_valid(self):
        text = '这里是说明\n[{"name": "ALT", "lower": null, "upper": 40, "unit": "U/L"}]\n完毕'
        arr = _extract_json_array(text)
        self.assertEqual(len(arr), 1)
        self.assertEqual(arr[0]["name"], "ALT")


class SyncProtectionTests(unittest.TestCase):
    """失败不破坏旧数据的空结果保护。"""

    @patch("app.services.reference_standard._sync_from_llm", side_effect=RuntimeError("timeout"))
    def test_empty_items_raises_and_keeps_old_data(self, _llm):
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        db.query.return_value.filter.return_value.first.return_value = doc
        # 文档含 current chunks，但都是无法确定性解析的行（如章节标题）
        chunk = MagicMock()
        chunk.content = "## 肝功能指标\n参考范围以检验科最新发布为准"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with self.assertRaises(ValueError):
            sync_reference_ranges(db, 1)
        # 空结果时不得调用 delete（旧行被保留）
        db.query.return_value.filter.return_value.delete.assert_not_called()

    @patch("app.services.reference_standard._sync_from_llm", side_effect=RuntimeError("timeout"))
    def test_partial_deterministic_plus_llm_failure_keeps_old_data(self, _llm):
        """确定性解析有部分命中 + LLM 失败：仍须整体 abort 保留旧数据，
        不能静默替换为不完整数据。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        db.query.return_value.filter.return_value.first.return_value = doc
        # 第一行确定性可命中（<21），第二行需要 LLM 但 LLM 抛异常
        chunk = MagicMock()
        chunk.content = "- TBIL（总胆红素）：<21 μmol/L\n（此行为补充说明，需 LLM 解析）"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with self.assertRaises(ValueError):
            sync_reference_ranges(db, 1)
        # 即使确定性有部分命中，LLM 失败时也不得 delete 旧行
        db.query.return_value.filter.return_value.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
