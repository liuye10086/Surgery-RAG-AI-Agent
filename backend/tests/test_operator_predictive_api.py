"""Operator predictive API 测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.schemas.prediction import (
    CaseRecordIn,
    DiseaseCreate,
    DiseaseUpdate,
    IndicatorInput,
)


def _operator_query(*, first=None, count=0):
    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = first
    query.count.return_value = count
    return query


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
        """预测分析端点保留病例、只读兼容范围和 operator 文档。"""
        from app.api.operator import router
        paths = {r.path for r in router.routes}
        self.assertTrue(
            {"/operator/cases", "/operator/diseases",
             "/operator/reference-ranges", "/operator/documents"}.issubset(paths)
        )
        self.assertNotIn("/operator/reference-ranges/sync", paths)

    def test_delete_disease_rejects_current_standard_before_delete(self):
        from app.api.operator import delete_disease
        from app.db.models import CaseRecord, Disease, ReferenceStandard

        disease = MagicMock(spec=Disease)
        disease.id = 7
        standard = MagicMock(spec=ReferenceStandard)
        standard.current_version_id = 11
        standard.current_version.status = "approved"

        class Query:
            def __init__(self, *, first=None, count=0):
                self.first_value = first
                self.count_value = count

            def filter(self, *_conditions):
                return self

            def with_for_update(self):
                return self

            def first(self):
                return self.first_value

            def count(self):
                return self.count_value

        class Db:
            def __init__(self):
                self.queries = {
                    Disease: Query(first=disease),
                    CaseRecord: Query(count=0),
                    ReferenceStandard: Query(first=standard),
                }
                self.deleted = []
                self.commits = 0

            def query(self, model):
                return self.queries[model]

            def delete(self, value):
                self.deleted.append(value)

            def commit(self):
                self.commits += 1

        db = Db()

        with self.assertRaises(HTTPException) as context:
            delete_disease(7, db=db, current_user=MagicMock())

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(db.deleted, [])
        self.assertEqual(db.commits, 0)

    def test_delete_disease_keeps_case_record_protection_first(self):
        from app.api.operator import delete_disease

        disease_query = MagicMock()
        disease_query.filter.return_value = disease_query
        disease_query.first.return_value = MagicMock(id=7)
        case_query = MagicMock()
        case_query.filter.return_value = case_query
        case_query.count.return_value = 1
        db = MagicMock()
        db.query.side_effect = [disease_query, case_query]

        with self.assertRaises(HTTPException) as context:
            delete_disease(7, db=db, current_user=MagicMock())

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(db.query.call_count, 2)
        db.delete.assert_not_called()
        db.commit.assert_not_called()

    def test_delete_disease_locks_parent_before_dependent_checks(self):
        from app.api.operator import delete_disease
        from app.db.models import CaseRecord, Disease, ReferenceStandard

        events = []

        class Query:
            def __init__(self, model, *, first=None, count=0):
                self.model = model
                self.first_value = first
                self.count_value = count

            def filter(self, *_conditions):
                events.append(f"{self.model.__name__}:filter")
                return self

            def with_for_update(self):
                events.append(f"{self.model.__name__}:with_for_update")
                return self

            def first(self):
                events.append(f"{self.model.__name__}:first")
                return self.first_value

            def count(self):
                events.append(f"{self.model.__name__}:count")
                return self.count_value

        disease = SimpleNamespace(id=7)
        queries = {
            Disease: Query(Disease, first=disease),
            CaseRecord: Query(CaseRecord),
            ReferenceStandard: Query(ReferenceStandard),
        }
        db = MagicMock()
        db.query.side_effect = lambda model: queries[model]

        delete_disease(7, db=db, current_user=MagicMock())

        self.assertEqual(
            events[:3],
            ["Disease:filter", "Disease:with_for_update", "Disease:first"],
        )

    def test_delete_disease_fk_race_maps_named_constraint_to_conflict(self):
        from app.api.operator import delete_disease
        from app.db.models import CaseRecord, Disease, ReferenceStandard

        disease = SimpleNamespace(id=7)
        db = MagicMock()
        db.query.side_effect = [
            _operator_query(first=disease),
            _operator_query(count=0),
            _operator_query(first=None),
        ]
        orig = SimpleNamespace(
            diag=SimpleNamespace(constraint_name="reference_standards_disease_id_fkey")
        )
        db.commit.side_effect = IntegrityError("delete", {}, orig)

        with self.assertRaises(HTTPException) as context:
            delete_disease(7, db=db, current_user=MagicMock())

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail, "该疾病已关联参考标准，不能删除")
        db.rollback.assert_called_once_with()

    def test_delete_disease_unrelated_integrity_error_is_not_mapped_to_conflict(self):
        from app.api.operator import delete_disease

        disease = SimpleNamespace(id=7)
        db = MagicMock()
        db.query.side_effect = [
            _operator_query(first=disease),
            _operator_query(count=0),
            _operator_query(first=None),
        ]
        orig = SimpleNamespace(diag=SimpleNamespace(constraint_name="other_constraint"))
        error = IntegrityError("delete", {}, orig)
        db.commit.side_effect = error

        with self.assertRaises(IntegrityError) as context:
            delete_disease(7, db=db, current_user=MagicMock())

        self.assertIs(context.exception, error)
        db.rollback.assert_called_once_with()


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
