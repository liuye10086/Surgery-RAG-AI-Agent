import unittest
import inspect
from types import SimpleNamespace

from app.db.models import Document as DocumentModel
from app.rag import pipeline
from app.rag.vectorstore import vector_id_for_chunk


class VectorGenerationTests(unittest.TestCase):
    def test_pipeline_uses_business_document_model_for_generation_filter(self):
        self.assertIs(pipeline.DocumentModel, DocumentModel)

    def test_vector_id_contains_document_generation_and_chunk(self):
        chunk = SimpleNamespace(id=9, document_id=12, generation=3)
        self.assertEqual(
            vector_id_for_chunk(chunk),
            "document-12-generation-3-chunk-9",
        )

    def test_missing_generation_defaults_to_one(self):
        chunk = SimpleNamespace(id=9, document_id=12)
        self.assertEqual(
            vector_id_for_chunk(chunk),
            "document-12-generation-1-chunk-9",
        )

    def test_search_filters_current_generation_before_limiting_candidates(self):
        for search in (pipeline._vector_search, pipeline._fulltext_search):
            source = inspect.getsource(search)
            sql_source = source[source.index('sql = text('):source.index('rows = db.execute(')]
            limit_position = sql_source.index("LIMIT :top_k")
            self.assertLess(sql_source.index("JOIN chunks"), limit_position)
            self.assertLess(sql_source.index("JOIN documents"), limit_position)
            self.assertLess(sql_source.index("is_current IS TRUE"), limit_position)
            self.assertLess(sql_source.index("active_generation"), limit_position)


if __name__ == "__main__":
    unittest.main()
