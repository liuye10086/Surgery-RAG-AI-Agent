"""Operator API 端点单元测试。"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


class TestOperatorSchemas(unittest.TestCase):
    """Pydantic Schema 验证测试。"""

    def test_generate_request_valid(self):
        """最小有效请求 → 通过校验。"""
        from app.schemas.operator import ReportGenerateRequest

        req = ReportGenerateRequest(query="测试问题")
        self.assertEqual(req.query, "测试问题")
        self.assertEqual(req.analysis_backend, "llm")
        self.assertIsNone(req.department_ids)

    def test_generate_request_with_departments(self):
        """含科室选择 → 通过校验。"""
        from app.schemas.operator import ReportGenerateRequest

        req = ReportGenerateRequest(query="test", department_ids=[1, 2])
        self.assertEqual(req.department_ids, [1, 2])

    def test_generate_request_empty_query_blocked(self):
        """空问题 → 校验失败。"""
        from app.schemas.operator import ReportGenerateRequest
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ReportGenerateRequest(query="")

    def test_generate_request_query_too_long_blocked(self):
        """超长问题 → 校验失败。"""
        from app.schemas.operator import ReportGenerateRequest
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ReportGenerateRequest(query="x" * 2001)

    def test_generate_request_invalid_backend_blocked(self):
        """非法 analysis_backend → 校验失败。"""
        from app.schemas.operator import ReportGenerateRequest
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ReportGenerateRequest(query="test", analysis_backend="invalid")

    def test_generate_request_empty_department_ids_normalized(self):
        """空 department_ids 列表 → 规范化为 None。"""
        from app.schemas.operator import ReportGenerateRequest

        req = ReportGenerateRequest(query="test", department_ids=[])
        self.assertIsNone(req.department_ids)

    def test_report_out_from_attributes(self):
        """ReportOut 可从 ORM 对象构造。"""
        from app.schemas.operator import ReportOut

        mock = MagicMock()
        mock.id = 1
        mock.user_id = 42
        mock.title = "测试报告"
        mock.query = "测试问题"
        mock.department_ids = [1]
        mock.content = "# 报告内容"
        mock.sources = []
        mock.retrieval_meta = {}
        mock.status = "completed"
        mock.error_message = None
        mock.download_count = 0
        mock.created_at = "2026-01-01T00:00:00"
        mock.updated_at = "2026-01-01T00:00:00"

        out = ReportOut.model_validate(mock)
        self.assertEqual(out.id, 1)
        self.assertEqual(out.status, "completed")

    def test_report_list_item_excludes_content(self):
        """ReportListItem 不包含 content（减少传输量）。"""
        from app.schemas.operator import ReportListItem

        # ReportListItem 定义中无 content 字段即为验证通过
        fields = ReportListItem.model_fields
        self.assertNotIn("content", fields)
        self.assertIn("id", fields)
        self.assertIn("status", fields)


class TestOperatorRouterSetup(unittest.TestCase):
    """路由注册测试。"""

    def test_router_has_5_endpoints(self):
        """operator router 包含 5 个路由端点。"""
        from app.api.operator import router

        # 5 个路由注册（POST/GET 可能共享路径，但路由数 = 端点注册数）
        self.assertEqual(len(router.routes), 5,
                         f"Expected 5 routes, got {len(router.routes)}")

    def test_router_prefix_is_operator(self):
        """路由前缀为 /operator。"""
        from app.api.operator import router

        self.assertEqual(router.prefix, "/operator")

    def test_all_routes_have_operator_prefix(self):
        """所有路由以 /operator 开头。"""
        from app.api.operator import router

        for route in router.routes:
            self.assertTrue(
                route.path.startswith("/operator"),
                f"Route {route.path} does not start with /operator",
            )


class TestMainAppRegistration(unittest.TestCase):
    """main.py 路由注册验证。"""

    def test_operator_router_registered(self):
        """operator router 已在 main.py 注册。"""
        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)

        app = main_mod.app
        operator_paths = [
            r.path for r in app.routes if "/operator" in r.path
        ]
        self.assertGreaterEqual(
            len(operator_paths), 1,
            "operator routes not found in app"
        )


if __name__ == "__main__":
    unittest.main()
