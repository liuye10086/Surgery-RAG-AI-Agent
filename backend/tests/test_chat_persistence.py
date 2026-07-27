import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.chat import persist_user_message


class _FakeQuery:
    def __init__(self, existing):
        self.existing = existing

    def filter(self, *args):
        return self

    def first(self):
        return self.existing


class _FakeDb:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.commit_count = 0

    def query(self, model):
        return _FakeQuery(self.existing)

    def add(self, message):
        self.added.append(message)

    def commit(self):
        self.commit_count += 1

    def refresh(self, message):
        if message.id is None:
            message.id = 101


class UserMessagePersistenceTests(unittest.TestCase):
    def test_new_request_persists_one_user_message(self):
        db = _FakeDb()
        message = persist_user_message(db, 7, "术后多久复查？", "req-1")
        self.assertEqual(message.role, "user")
        self.assertEqual(message.client_request_id, "req-1")
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.commit_count, 1)

    def test_duplicate_request_reuses_existing_message(self):
        existing = SimpleNamespace(
            id=88,
            session_id=7,
            role="user",
            content="术后多久复查？",
            client_request_id="req-1",
        )
        db = _FakeDb(existing=existing)
        message = persist_user_message(db, 7, "术后多久复查？", "req-1")
        self.assertIs(message, existing)
        self.assertEqual(db.added, [])
        self.assertEqual(db.commit_count, 0)

    def test_duplicate_request_with_other_content_is_rejected(self):
        existing = SimpleNamespace(
            id=88,
            session_id=7,
            role="user",
            content="原问题",
            client_request_id="req-1",
        )
        with self.assertRaises(HTTPException) as ctx:
            persist_user_message(_FakeDb(existing), 7, "不同问题", "req-1")
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
