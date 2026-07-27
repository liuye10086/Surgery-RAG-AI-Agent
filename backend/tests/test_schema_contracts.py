import unittest

from pydantic import ValidationError

from app.db.models import Chunk, Document, Message
from app.schemas.chat import AskRequest


class SchemaContractTests(unittest.TestCase):
    def test_generation_columns_exist(self):
        self.assertTrue(hasattr(Document, "active_generation"))
        self.assertTrue(hasattr(Chunk, "generation"))

    def test_message_idempotency_column_exists(self):
        self.assertTrue(hasattr(Message, "client_request_id"))

    def test_ask_request_accepts_client_request_id(self):
        req = AskRequest(content="术后多久复查？", client_request_id="req-123")
        self.assertEqual(req.client_request_id, "req-123")

    def test_ask_request_rejects_blank_client_request_id(self):
        with self.assertRaises(ValidationError):
            AskRequest(content="术后多久复查？", client_request_id="   ")


if __name__ == "__main__":
    unittest.main()
