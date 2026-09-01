import unittest
from pathlib import Path

from pydantic import ValidationError

from app.db.base import Base
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

    def test_document_out_has_access_scope(self):
        from app.schemas.document import DocumentOut
        self.assertIn("access_scope", DocumentOut.model_fields)

    def test_clean_install_schema_declares_dedicated_standard_documents(self):
        schema = (Path(__file__).resolve().parents[2] / "database/schema.sql").read_text(
            encoding="utf-8"
        )
        for literal in (
            "standard_documents",
            "content_hash",
            "standard_document_id",
            "uq_reference_standard_versions_standard_document",
        ):
            self.assertIn(literal, schema)

    def test_clean_install_schema_restricts_deleting_disease_with_standard(self):
        schema = (Path(__file__).resolve().parents[2] / "database/schema.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "disease_id INTEGER NOT NULL CONSTRAINT "
            "reference_standards_disease_id_fkey "
            "REFERENCES diseases(id) ON DELETE RESTRICT",
            schema,
        )

    def test_clean_install_schema_contains_all_orm_business_columns(self):
        schema = (Path(__file__).resolve().parents[2] / "database/schema.sql").read_text(
            encoding="utf-8"
        )
        for table in Base.metadata.tables.values():
            table_match = schema.find(f"CREATE TABLE IF NOT EXISTS {table.name} (")
            self.assertGreaterEqual(table_match, 0, table.name)
            table_end = schema.find("\n);", table_match)
            self.assertGreater(table_end, table_match, table.name)
            table_sql = schema[table_match:table_end]
            for column in table.columns:
                self.assertRegex(
                    table_sql,
                    rf"(?m)^    {column.name}\s+",
                    f"{table.name}.{column.name}",
                )


if __name__ == "__main__":
    unittest.main()
