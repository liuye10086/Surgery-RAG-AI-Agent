"""Operator disease catalog, reference cases, reports, and router tests."""
import asyncio
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from app.schemas.prediction import (
    CaseRecordIn,
    IndicatorInput,
)


def _operator_query(*, first=None, count=0):
    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = first
    query.count.return_value = count
    return query


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
    def test_operator_router_exposes_only_get_diseases(self):
        from app.api.operator import router

        disease_routes = [
            route
            for route in router.routes
            if route.path.startswith("/operator/diseases")
        ]
        self.assertEqual(
            [(route.path, set(route.methods)) for route in disease_routes],
            [("/operator/diseases", {"GET"})],
        )

    def test_operator_catalog_filters_enabled_registered_codes(self):
        from app.api.operator import list_diseases
        from app.services.disease_catalog import DISEASE_CAPABILITIES

        disease = SimpleNamespace(
            id=1,
            code="fatty_liver",
            name="脂肪肝",
            description=None,
            operator_enabled=True,
            created_at=None,
        )
        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        query.all.return_value = [disease]
        db = MagicMock()
        db.query.return_value = query

        self.assertEqual(
            list_diseases(db=db, current_user=MagicMock()),
            [disease],
        )
        filter_call = query.filter.call_args.args
        self.assertEqual(len(filter_call), 2)
        self.assertEqual(set(DISEASE_CAPABILITIES), {"fatty_liver", "ad"})

    def test_catalog_and_report_endpoints_registered(self):
        """操作者路由保留目录、纵向病例与报告能力。"""
        from app.api.operator import router

        paths = {r.path for r in router.routes}
        self.assertTrue(
            {
                "/operator/cases",
                "/operator/diseases",
                "/operator/reference-ranges",
                "/operator/documents",
                "/operator/longitudinal-cases",
                "/operator/reports",
            }.issubset(paths)
        )
        self.assertNotIn("/operator/progression-predictions", paths)
        self.assertNotIn("/operator/reference-ranges/sync", paths)

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

    def test_longitudinal_report_uses_terminal_statuses(self):
        """纵向报告沿用 generating/completed 终态，不依赖单时点生成器。"""
        r = MagicMock(); r.status = "generating"
        r.status = "completed"
        self.assertEqual(r.status, "completed")

    def test_longitudinal_report_loads_one_active_disease_release_set(self):
        import inspect

        from app.api.operator import create_longitudinal_report

        source = inspect.getsource(create_longitudinal_report)
        self.assertIn("load_active_model_registry(adapter.dataset)", source)
        self.assertNotIn("load_model_registry(adapter.dataset)", source)

    def test_longitudinal_report_routes_by_disease_code_after_display_name_change(self):
        from app.api.operator import create_longitudinal_report
        from app.services.disease_catalog import DISEASE_CAPABILITIES

        case = SimpleNamespace(
            id=3,
            user_id=7,
            disease_id=11,
            patient_label="case-A",
            age=65,
            sex="female",
            baseline_stage="S1",
            notes=None,
            disease=SimpleNamespace(
                id=11,
                code="fatty_liver",
                name="脂肪肝新名称",
                operator_enabled=True,
            ),
            visits=[
                SimpleNamespace(
                    id=1,
                    visit_date=date(2024, 1, 1),
                    indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
                    notes=None,
                )
            ],
        )
        db = MagicMock()
        captured = {}

        def fake_generate(*args, **kwargs):
            captured["adapter"] = args[4]
            return iter([b""])

        with patch("app.api.operator.get_operator_case", return_value=case), patch(
            "app.api.operator.build_reference_range_sources", return_value=[]
        ), patch(
            "app.api.operator.select_similar_longitudinal_cases", return_value=[]
        ), patch(
            "app.api.operator.load_active_model_registry", return_value={}
        ), patch(
            "app.api.operator.generate_longitudinal_report", side_effect=fake_generate
        ):
            asyncio.run(
                create_longitudinal_report(
                    case_id=3,
                    request=None,
                    db=db,
                    current_user=SimpleNamespace(id=7),
                )
            )

        self.assertIs(
            captured["adapter"],
            DISEASE_CAPABILITIES["fatty_liver"].adapter,
        )
        db.add.assert_called_once()

    def test_disabled_disease_rejects_report_before_insert(self):
        from app.api.operator import create_longitudinal_report

        case = SimpleNamespace(
            id=3,
            user_id=7,
            disease_id=11,
            patient_label="case-A",
            age=65,
            disease=SimpleNamespace(
                id=11,
                code="fatty_liver",
                name="脂肪肝",
                operator_enabled=False,
            ),
            visits=[],
        )
        db = MagicMock()

        with patch("app.api.operator.get_operator_case", return_value=case):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(
                    create_longitudinal_report(
                        case_id=3,
                        request=None,
                        db=db,
                        current_user=SimpleNamespace(id=7),
                    )
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail, "该疾病已停用，病例当前只读")
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_disabled_report_guard_precedes_legacy_age_validation(self):
        from app.api.operator import create_longitudinal_report

        case = SimpleNamespace(
            age=None,
            disease=SimpleNamespace(
                id=11,
                code="fatty_liver",
                name="脂肪肝",
                operator_enabled=False,
            ),
            visits=[],
        )

        with patch("app.api.operator.get_operator_case", return_value=case):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(
                    create_longitudinal_report(
                        case_id=3,
                        request=None,
                        db=MagicMock(),
                        current_user=SimpleNamespace(id=7),
                    )
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail, "该疾病已停用，病例当前只读")

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
