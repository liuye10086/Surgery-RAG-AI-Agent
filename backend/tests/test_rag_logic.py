import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from app.rag.pipeline import hybrid_search
from app.services.llm_client import _has_sufficient_knowledge_for_docs, parse_citations


def _doc(**metadata):
    return Document(page_content="test", metadata=metadata)


class KnowledgeSufficiencyTests(unittest.TestCase):
    def test_empty_documents_are_insufficient(self):
        self.assertFalse(_has_sufficient_knowledge_for_docs([]))

    def test_high_vector_score_is_sufficient(self):
        self.assertTrue(_has_sufficient_knowledge_for_docs([_doc(vector_score=0.9)]))

    def test_multiple_low_positive_vector_scores_are_insufficient(self):
        docs = [_doc(vector_score=0.1), _doc(vector_score=0.2)]
        self.assertFalse(_has_sufficient_knowledge_for_docs(docs))

    def test_dual_match_near_threshold_is_sufficient(self):
        docs = [_doc(vector_score=0.60, vector_rank=1, fulltext_rank=1)]
        self.assertTrue(_has_sufficient_knowledge_for_docs(docs))

    def test_strong_fulltext_match_is_sufficient(self):
        docs = [_doc(vector_score=None, fulltext_score=0.3, fulltext_rank=1)]
        self.assertTrue(_has_sufficient_knowledge_for_docs(docs))


class CitationParsingTests(unittest.TestCase):
    def test_parses_merged_citations_with_common_separators(self):
        text = "step[5, 6] next[7\uff0c8] final[9\u300110]"

        self.assertEqual(parse_citations(text, total=10), [5, 6, 7, 8, 9, 10])

    def test_deduplicates_and_filters_out_of_range_citations(self):
        text = "step[2][2] other[3, 99] and[0\u30014]"

        self.assertEqual(parse_citations(text, total=4), [2, 3, 4])


class HybridSearchTests(unittest.TestCase):
    @patch("app.rag.pipeline._fulltext_search", return_value=[])
    @patch("app.rag.pipeline._vector_search", return_value=[])
    def test_normal_empty_search_returns_empty_list(self, _vector, _fulltext):
        self.assertEqual(hybrid_search(object(), "不存在的问题"), [])

    @patch("app.rag.pipeline._fulltext_search", side_effect=RuntimeError("fulltext"))
    @patch("app.rag.pipeline._vector_search", side_effect=RuntimeError("vector"))
    def test_both_failed_raises(self, _vector, _fulltext):
        with self.assertRaises(RuntimeError):
            hybrid_search(object(), "检索故障")


if __name__ == "__main__":
    unittest.main()
