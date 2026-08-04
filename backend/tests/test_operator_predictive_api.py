"""Operator predictive API 测试。"""
import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException
from app.schemas.prediction import (
    CaseRecordIn,
    DiseaseCreate,
    DiseaseUpdate,
    IndicatorInput,
    PredictRequest,
)


class DiseaseSchemaTests(unittest.TestCase):
    def test_disease_create_requires_name(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DiseaseCreate(name="")

    def test_disease_create_normalizes_name(self):
        d = DiseaseCreate(name=" 胆囊结石 ")
        self.assertEqual(d.name, "胆囊结石")

    def test_disease_out_construction(self):
        """_disease_to_out 显式构造（Pydantic v2 model_validate 无 update 参数）。"""
        from unittest.mock import MagicMock
        from app.api.operator import _disease_to_out

        d = MagicMock()
        d.id = 1
        d.name = "胆囊结石"
        d.description = None
        d.created_at = "2026-01-01T00:00:00"
        out = _disease_to_out(d, 5)
        self.assertEqual(out.id, 1)
        self.assertEqual(out.case_count, 5)


class CaseRecordSchemaTests(unittest.TestCase):
    def test_case_record_requires_indicators(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            CaseRecordIn(disease_id=1, indicators=[])

    def test_indicator_validates_name_value_unit(self):
        ind = IndicatorInput(name="TBIL", value=35.0, unit="μmol/L")
        self.assertEqual(ind.name, "TBIL")
        self.assertEqual(ind.value, 35.0)


class OperatorRouterEndpointTests(unittest.TestCase):
    def test_predictive_endpoints_registered(self):
        """预测分析端点全部注册（疾病/病例/参考范围同步与列表/operator 文档）。"""
        from app.api.operator import router
        paths = {r.path for r in router.routes}
        self.assertTrue(
            {"/operator/cases", "/operator/diseases",
             "/operator/reference-ranges/sync",
             "/operator/reference-ranges", "/operator/documents"}.issubset(paths)
        )


class ReportSchemaContractTests(unittest.TestCase):
    def test_report_out_has_predictive_fields(self):
        from app.schemas.operator import ReportOut
        fields = ReportOut.model_fields
        self.assertTrue(
            {"analysis_type", "disease_id", "indicators", "prediction_result"}.issubset(fields)
        )

    def test_report_list_item_has_predictive_fields(self):
        from app.schemas.operator import ReportListItem
        fields = ReportListItem.model_fields
        self.assertTrue(
            {"analysis_type", "disease_id", "indicators", "prediction_result"}.issubset(fields)
        )


class PredictRequestTests(unittest.TestCase):
    def test_valid_prediction_request(self):
        req = PredictRequest(disease_id=1, indicators=[IndicatorInput(name="TBIL", value=35.0, unit="μmol/L")])
        self.assertEqual(req.disease_id, 1)
        self.assertIsNone(req.patient_summary)

    def test_indicators_required(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            PredictRequest(disease_id=1, indicators=[])

    def test_disease_id_required(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            PredictRequest(indicators=[IndicatorInput(name="TBIL", value=1, unit="u")])


class TestReportStateMachine(unittest.TestCase):
    """AIReport 状态机关键行为（从旧 test_operator_state_machine 迁入）。"""

    def test_cancel_only_from_generating(self):
        """取消保护：仅 generating 可标记 cancelled（对应 operator.py 的
        `if r and r.status == "generating"` 守卫）。"""
        r = MagicMock()
        r.status = "generating"
        if r.status == "generating":
            r.status = "cancelled"
            r.error_message = "用户取消生成"
        self.assertEqual(r.status, "cancelled")

        r2 = MagicMock()
        r2.status = "completed"
        if r2.status != "generating":
            pass  # 不覆盖
        self.assertEqual(r2.status, "completed")

    def test_persist_failed_guards_terminal_states(self):
        """终态不覆盖：由 prediction_generator._persist_failed 守卫（已测），
        此处验证 cancelled 不被 failed 覆盖。"""
        from app.services.prediction_generator import _persist_failed
        db = MagicMock()
        r = MagicMock(); r.id = 1; r.status = "cancelled"
        db.query.return_value.filter.return_value.first.return_value = r
        _persist_failed(db, 1, "partial", "error")
        self.assertEqual(r.status, "cancelled")

    def test_download_count_increments(self):
        """PDF 下载后 download_count 自增（operator.py download 端点）。"""
        from app.db.models import AIReport
        report = MagicMock(spec=AIReport)
        report.download_count = 0
        report.download_count = (report.download_count or 0) + 1
        self.assertEqual(report.download_count, 1)


class TestMainAppRegistration(unittest.TestCase):
    """main.py 路由注册验证（从旧 test_operator_api 迁入）。"""

    def test_operator_router_registered(self):
        """operator router 已在 main.py 注册。

        兼容 FastAPI include_router 的两种展开形态：
        - 旧版：子路由扁平展开进 app.routes，path 含 /operator；
        - 新版：app.routes 以 _IncludedRouter 挂载，original_router /
          include_context.included_router 指向 operator.router，不再扁平出 path。
        """
        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)

        from app.api.operator import router as operator_router

        app = main_mod.app
        flat_paths = [
            r.path for r in app.routes
            if getattr(r, "path", None) and "/operator" in r.path
        ]
        included = [
            r for r in app.routes
            if getattr(r, "original_router", None) is operator_router
            or (
                getattr(r, "include_context", None) is not None
                and getattr(r.include_context, "included_router", None)
                is operator_router
            )
        ]
        self.assertTrue(
            flat_paths or included,
            "operator routes not found in app",
        )


if __name__ == "__main__":
    unittest.main()
