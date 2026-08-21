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
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": False, "sex": None}],
        )

    def test_parse_range_form(self):
        # 区间 → 两端 inclusive=True
        self.assertEqual(
            parse_reference_segment("WBC（白细胞计数）：3.5-9.5 ×10⁹/L"),
            [{"indicator_name": "WBC", "name_cn": "白细胞计数", "unit": "×10⁹/L",
              "lower": 3.5, "upper": 9.5, "lower_inclusive": True, "upper_inclusive": True, "sex": None}],
        )

    def test_parse_le_form_inclusive_upper(self):
        # ≤21 → upper_inclusive=True（与 <21 的 upper_inclusive=False 区分）
        self.assertEqual(
            parse_reference_segment("ALP（碱性磷酸酶）：≤21 μmol/L"),
            [{"indicator_name": "ALP", "name_cn": "碱性磷酸酶", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": True, "sex": None}],
        )

    def test_parse_gt_form_exclusive_lower(self):
        # 严格下限：>140 → lower=140, lower_inclusive=False
        self.assertEqual(
            parse_reference_segment("SBP（收缩压）：>140 mmHg"),
            [{"indicator_name": "SBP", "name_cn": "收缩压", "unit": "mmHg",
              "lower": 140.0, "upper": None, "lower_inclusive": False, "upper_inclusive": True, "sex": None}],
        )

    def test_parse_ge_form_inclusive_lower(self):
        # 含边界下限：≥140 → lower=140, lower_inclusive=True
        self.assertEqual(
            parse_reference_segment("SBP（收缩压）：≥140 mmHg"),
            [{"indicator_name": "SBP", "name_cn": "收缩压", "unit": "mmHg",
              "lower": 140.0, "upper": None, "lower_inclusive": True, "upper_inclusive": True, "sex": None}],
        )

    def test_parse_list_prefix_line(self):
        # 列表前缀行也应被确定性解析命中（- TBIL...）
        self.assertEqual(
            parse_reference_segment("- TBIL（总胆红素）：<21 μmol/L"),
            [{"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": False, "sex": None}],
        )

    def test_parse_unparseable_returns_empty(self):
        self.assertEqual(parse_reference_segment("参考标准为临床公认值"), [])

    def test_extract_json_array_valid(self):
        text = '这里是说明\n[{"name": "ALT", "lower": null, "upper": 40, "unit": "U/L"}]\n完毕'
        arr = _extract_json_array(text)
        self.assertEqual(len(arr), 1)
        self.assertEqual(arr[0]["name"], "ALT")

    def test_parse_en_dash_range_with_filler_word(self):
        # 真实标准文档常见的 en-dash（–，U+2013）+ "约" 修饰词，
        # 原正则只认 ASCII '-'，会导致整行落入 LLM 路径丢失精确边界。
        result = parse_reference_segment("AST（谷草转氨酶）：约 15–40 U/L")
        self.assertEqual(result, [{
            "indicator_name": "AST", "name_cn": "谷草转氨酶", "unit": "U/L",
            "lower": 15.0, "upper": 40.0, "lower_inclusive": True, "upper_inclusive": True,
            "sex": None,
        }])

    def test_parse_sex_segmented_range_splits_into_two_records(self):
        # "男性约 9–50；女性约 7–40" 应拆成两条 sex 分别为 male/female 的记录，
        # 而不是被当成解析失败或产出一条无意义的合并范围。
        result = parse_reference_segment("ALT（谷丙转氨酶）：男性约 9–50；女性约 7–40 U/L")
        self.assertEqual(len(result), 2)
        male = next(r for r in result if r["sex"] == "male")
        female = next(r for r in result if r["sex"] == "female")
        self.assertEqual((male["lower"], male["upper"]), (9.0, 50.0))
        self.assertEqual((female["lower"], female["upper"]), (7.0, 40.0))

    def test_parse_sex_segmented_strict_bound(self):
        result = parse_reference_segment("HDL-C（高密度脂蛋白胆固醇）：男性 > 1.00；女性 > 1.30 mmol/L")
        male = next(r for r in result if r["sex"] == "male")
        self.assertEqual(male["lower"], 1.0)
        self.assertFalse(male["lower_inclusive"])


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

    @patch("app.services.reference_standard._sync_from_llm", return_value=[])
    def test_partial_deterministic_plus_empty_llm_result_keeps_old_data(self, _llm):
        """确定性解析有部分命中 + LLM 返回空（输出非法 JSON/无有效条目）：
        无法证明空结果合法，仍须整体 abort 保留旧数据，不能以部分结果覆盖。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        db.query.return_value.filter.return_value.first.return_value = doc
        chunk = MagicMock()
        chunk.content = "- TBIL（总胆红素）：<21 μmol/L\n（此行为补充说明，需 LLM 解析）"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with self.assertRaises(ValueError):
            sync_reference_ranges(db, 1)
        # LLM 返回空也不得 delete 旧行
        db.query.return_value.filter.return_value.delete.assert_not_called()


class TableParsingTests(unittest.TestCase):
    """_parse_tables_from_docx 对真实脂肪肝/AD 表格格式的解析。"""

    def _build_docx(self, tmp_path, header, rows):
        from docx import Document
        doc = Document()
        table = doc.add_table(rows=1 + len(rows), cols=len(header))
        for c, h in enumerate(header):
            table.rows[0].cells[c].text = h
        for r, row in enumerate(rows, start=1):
            for c, val in enumerate(row):
                table.rows[r].cells[c].text = val
        doc.save(tmp_path)

    def test_fatty_liver_table_with_sex_segmented_range(self):
        import tempfile, os
        from app.services.reference_standard import _parse_tables_from_docx
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "standard.docx")
            self._build_docx(path,
                ["metric_name（指标名称）", "normal_range（正常指标）", "fatty_liver_grade（脂肪肝标准）", "unit（单位）"],
                [["ALT（谷丙转氨酶）", "男性约 9–50；女性约 7–40", "不用于单独分级", "U/L"]],
            )
            items = _parse_tables_from_docx(path)
            self.assertEqual(len(items), 2)
            sexes = {it["sex"] for it in items}
            self.assertEqual(sexes, {"male", "female"})
            for it in items:
                self.assertEqual(it["indicator_name"], "ALT")

    def test_ad_table_only_imports_normal_or_control_column(self):
        import tempfile, os
        from app.services.reference_standard import _parse_tables_from_docx
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "standard.docx")
            self._build_docx(path,
                ["indicator_name（指标名称）", "normal_or_control（正常/对照）",
                 "ad_pattern（AD表现）", "evidence_type（证据属性）", "applicability（适用限制）"],
                [["MMSE（简易精神状态检查）", "常见为≥27分", "≤24分提示痴呆", "认知筛查", "-"]],
            )
            items = _parse_tables_from_docx(path)
            # ad_pattern 列不应产生任何 ReferenceRange（方向性描述，非对称数值区间）
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["indicator_name"], "MMSE")
            self.assertEqual(items[0]["lower"], 27.0)

    def test_multiword_indicator_name_not_truncated(self):
        import tempfile, os
        from app.services.reference_standard import _parse_tables_from_docx
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "standard.docx")
            self._build_docx(path,
                ["indicator_name（指标名称）", "normal_or_control（正常/对照）",
                 "ad_pattern（AD表现）", "evidence_type", "applicability"],
                [["FDG-PET SUVR（FDG-PET标准摄取值比）", "≥1.158", "<1.158", "单项研究阈值", "-"]],
            )
            items = _parse_tables_from_docx(path)
            self.assertEqual(items[0]["indicator_name"], "FDG-PET SUVR")


class SyncMergeDeduplicationTests(unittest.TestCase):
    """sync_reference_ranges 合并阶段的重复导入防护。"""

    def test_table_and_llm_extraction_of_same_row_deduplicated(self):
        """docx 表格行会被 parser.py 同时写入 chunk 文本（"| 单元格 |" 格式），
        这些行仍会喂给 LLM（因为纯叙述性 chunk 往往只能靠表格行本身让 LLM
        提取到内容——不能在合并前就跳过，否则 LLM 会因为看不到任何可提取
        内容而合法返回空，被误判为"提取失败"）。若表格解析器与 LLM 各自
        从同一行提取出等价范围，合并阶段应按逻辑键去重，不产出两条重复记录。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        doc.file_path = "/fake/path/standard.docx"
        db.query.return_value.filter.return_value.first.return_value = doc
        # chunk 内容模拟 parser.py 写入的表格行格式（不含性别分段，确定性解析器无法命中，
        # 因为该行以 "|" 开头，落入 LLM 路径）
        chunk = MagicMock()
        chunk.content = "| AST（谷草转氨酶） | 约 15–40 | 不用于单独分级 | U/L |"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with patch(
            "app.services.reference_standard._parse_tables_from_docx",
            return_value=[
                {"indicator_name": "AST", "name_cn": "谷草转氨酶", "unit": "U/L",
                 "lower": 15.0, "upper": 40.0, "lower_inclusive": True, "upper_inclusive": True, "sex": None},
            ],
        ), patch(
            "app.services.reference_standard._sync_from_llm",
            return_value=[
                {"indicator_name": "AST", "name_cn": "谷草转氨酶", "unit": "U/L",
                 "lower": 15.0, "upper": 40.0, "lower_inclusive": True, "upper_inclusive": True, "sex": None},
            ],
        ):
            result = sync_reference_ranges(db, 1)

        # 表格解析与 LLM 各产出一条等价范围，合并去重后只应插入一条
        self.assertEqual(result["inserted"], 1)

    def test_dedup_ignores_category_mismatch_between_table_and_llm(self):
        """真实场景复现：表格解析产出的范围 category 为空，但 LLM 从同一份
        叙述性文本（含章节标题）提取出等价范围时会填充 category（如章节名）。
        二者本应是同一条逻辑范围，若把 category 计入去重键，会因为
        None != "章节标题" 而被误判为两条不同记录，插入重复行。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        doc.file_path = None
        db.query.return_value.filter.return_value.first.return_value = doc
        chunk = MagicMock()
        chunk.content = "五、特殊情况\n| AST（谷草转氨酶） | 约 15–40 | 说明 | U/L |"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with patch(
            "app.services.reference_standard._sync_from_llm",
            return_value=[
                {"indicator_name": "AST", "name_cn": "谷草转氨酶", "unit": "U/L",
                 "lower": 15.0, "upper": 40.0, "lower_inclusive": True, "upper_inclusive": True,
                 "sex": None, "category": "特殊情况"},
            ],
        ):
            result = sync_reference_ranges(db, 1)

        self.assertEqual(result["inserted"], 1)

    def test_same_range_from_deterministic_and_llm_paths_is_deduplicated(self):
        """确定性解析与 LLM 路径若碰巧产出完全相同的范围（如文档正文重复出现
        同一标准），合并阶段应按逻辑键去重，不写入两条相同记录。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        doc.file_path = None
        db.query.return_value.filter.return_value.first.return_value = doc
        chunk = MagicMock()
        chunk.content = "- TBIL（总胆红素）：<21 μmol/L\n- TBIL（总胆红素）：<21 μmol/L"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        result = sync_reference_ranges(db, 1)
        self.assertEqual(result["inserted"], 1)

    def test_dedup_ignores_inclusive_flag_when_bound_is_none(self):
        """真实场景复现：表格解析与 LLM 对同一个 "<21" 形式的范围，
        lower 均为 None，但填的 lower_inclusive 默认值不同（True vs False）——
        lower 为 None 时 lower_inclusive 本身没有意义，不应据此判定为
        两条不同的范围。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        doc.file_path = None
        db.query.return_value.filter.return_value.first.return_value = doc
        chunk = MagicMock()
        chunk.content = "五、补充\n某无法确定性解析的段落"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with patch(
            "app.services.reference_standard._sync_from_llm",
            return_value=[
                {"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
                 "lower": None, "upper": 17.1, "lower_inclusive": True, "upper_inclusive": True, "sex": None},
                {"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
                 "lower": None, "upper": 17.1, "lower_inclusive": False, "upper_inclusive": True, "sex": None},
            ],
        ):
            result = sync_reference_ranges(db, 1)

        self.assertEqual(result["inserted"], 1)


if __name__ == "__main__":
    unittest.main()
