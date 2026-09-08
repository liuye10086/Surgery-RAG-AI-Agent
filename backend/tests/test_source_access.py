"""source_access 的 access_scope 隔离测试。"""
import unittest
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.source_access import (
    user_can_access_document,
    user_can_access_image,
)


@pytest.mark.parametrize("kind", ["document", "image"])
@pytest.mark.parametrize("role", ["ai_operator", "user"])
@pytest.mark.parametrize("has_source", [False, True])
def test_both_scope_operator_and_chat_permissions(kind, role, has_source):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(access_scope="both")
    sources = [{"document_id": 42, "images": [{"url": "/images/42/1/test.png"}]}]
    db.query.return_value.join.return_value.filter.return_value.all.return_value = [(sources,)] if has_source else []
    user = SimpleNamespace(id=1, role=role)
    actual = user_can_access_document(db, user, 42) if kind == "document" else user_can_access_image(db, user, 42, 1, "test.png")
    assert actual is (role == "ai_operator" or has_source)


class AccessScopeIsolationTests(unittest.TestCase):
    def _mock_db(self, access_scope):
        db = MagicMock()
        doc = MagicMock()
        doc.access_scope = access_scope
        db.query.return_value.filter.return_value.first.return_value = doc
        return db

    def test_operator_scope_document_rejected_for_chat_user(self):
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "patient"
        self.assertFalse(user_can_access_document(db, user, 42))

    def test_operator_scope_document_allowed_for_operator(self):
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "ai_operator"
        self.assertTrue(user_can_access_document(db, user, 42))

    def test_chat_scope_document_falls_through_to_sources(self):
        db = self._mock_db("chat")
        user = MagicMock(); user.id = 1; user.role = "patient"
        # 无历史 sources → 拒绝（chat 范围仍需被引用过才能读全文）
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        self.assertFalse(user_can_access_document(db, user, 42))

    def test_operator_scope_image_rejected_for_chat_user(self):
        """图片读取面同样受 scope 约束（/files/images/... 绕过路径回归保护）。"""
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "patient"
        self.assertFalse(user_can_access_image(db, user, 42, 1, "p1_0.png"))

    def test_operator_scope_image_allowed_for_operator(self):
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "ai_operator"
        self.assertTrue(user_can_access_image(db, user, 42, 1, "p1_0.png"))


if __name__ == "__main__":
    unittest.main()
