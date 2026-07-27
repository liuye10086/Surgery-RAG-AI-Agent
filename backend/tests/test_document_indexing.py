import unittest
from types import SimpleNamespace

from app.services.document_indexing import activate_generation


class _UpdateQuery:
    def __init__(self, rows):
        self.rows = rows
        self.predicates = []

    def filter(self, *predicates):
        self.predicates.extend(predicates)
        return self

    def update(self, values, synchronize_session=False):
        generation = None
        current = values.get("is_current")
        for row in self.rows:
            if current is False:
                row.is_current = False
            elif current is True and row.generation == generation:
                row.is_current = True
        return len(self.rows)


class _FakeDb:
    def __init__(self, chunks):
        self.chunks = chunks
        self.flush_count = 0

    def query(self, model):
        return _UpdateQuery(self.chunks)

    def flush(self):
        self.flush_count += 1


class GenerationActivationTests(unittest.TestCase):
    def test_activation_updates_document_generation(self):
        doc = SimpleNamespace(id=12, active_generation=1, status="chunked")
        chunks = [
            SimpleNamespace(document_id=12, generation=1, is_current=True),
            SimpleNamespace(document_id=12, generation=2, is_current=False),
        ]
        activate_generation(_FakeDb(chunks), doc, 2)
        self.assertEqual(doc.active_generation, 2)
        self.assertEqual(doc.status, "indexed")


if __name__ == "__main__":
    unittest.main()
