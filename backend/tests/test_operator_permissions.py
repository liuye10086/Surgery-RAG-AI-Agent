"""权限依赖单元测试。"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


class TestRequireAiOperator(unittest.TestCase):
    """require_ai_operator 依赖测试。"""

    def setUp(self):
        from app.api.deps import require_ai_operator
        self.dep = require_ai_operator

    def test_ai_operator_passes(self):
        """ai_operator 角色 → 通过。"""
        user = MagicMock()
        user.role = "ai_operator"
        result = self.dep(user)
        self.assertEqual(result, user)

    def test_admin_passes(self):
        """admin 角色 → 通过。"""
        user = MagicMock()
        user.role = "admin"
        result = self.dep(user)
        self.assertEqual(result, user)

    def test_regular_user_blocked(self):
        """普通用户 → 403。"""
        user = MagicMock()
        user.role = "user"
        with self.assertRaises(HTTPException) as ctx:
            self.dep(user)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_doctor_blocked(self):
        """医生角色 → 403（医生不是 ai_operator 角色）。

        注意：role='doctor' 是对患者端而言的，与 ai_operator 是两个维度。
        """
        user = MagicMock()
        user.role = "doctor"
        with self.assertRaises(HTTPException) as ctx:
            self.dep(user)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_patient_blocked(self):
        """患者角色 → 403。"""
        user = MagicMock()
        user.role = "patient"
        with self.assertRaises(HTTPException) as ctx:
            self.dep(user)
        self.assertEqual(ctx.exception.status_code, 403)


class TestRequireNotAiOperator(unittest.TestCase):
    """require_not_ai_operator 依赖测试。"""

    def setUp(self):
        from app.api.deps import require_not_ai_operator
        self.dep = require_not_ai_operator

    def test_ai_operator_blocked(self):
        """ai_operator → 403。"""
        user = MagicMock()
        user.role = "ai_operator"
        with self.assertRaises(HTTPException) as ctx:
            self.dep(user)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_passes(self):
        """admin → 通过。"""
        user = MagicMock()
        user.role = "admin"
        result = self.dep(user)
        self.assertEqual(result, user)

    def test_regular_user_passes(self):
        """普通用户 → 通过。"""
        user = MagicMock()
        user.role = "user"
        result = self.dep(user)
        self.assertEqual(result, user)

    def test_doctor_passes(self):
        """医生 → 通过。"""
        user = MagicMock()
        user.role = "doctor"
        result = self.dep(user)
        self.assertEqual(result, user)


class TestReportOwnerVerification(unittest.TestCase):
    """_verify_report_owner 归属校验测试。"""

    def setUp(self):
        from app.api.operator import _verify_report_owner
        self.func = _verify_report_owner

    def test_owner_passes(self):
        """报告所有者 → 不抛异常。"""
        report = MagicMock()
        report.user_id = 42
        user = MagicMock()
        user.id = 42
        self.func(report, user)  # 不抛异常

    def test_non_owner_raises_404(self):
        """非所有者 → 404（隐藏存在性）。"""
        report = MagicMock()
        report.user_id = 42
        user = MagicMock()
        user.id = 99
        with self.assertRaises(HTTPException) as ctx:
            self.func(report, user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_admin_not_owner_also_blocked(self):
        """admin 也看不到其他用户的报告。"""
        report = MagicMock()
        report.user_id = 42
        user = MagicMock()
        user.id = 99
        user.role = "admin"
        with self.assertRaises(HTTPException) as ctx:
            self.func(report, user)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
