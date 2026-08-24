from pathlib import Path
from types import SimpleNamespace

from app.services.standard_lifecycle import seed_standard_draft


def test_seed_draft_is_idempotent_for_same_content_hash(tmp_path):
    source = tmp_path / "ad.docx"
    source.write_bytes(b"docx-content")
    disease = SimpleNamespace(id=2, name="AD")
    document = SimpleNamespace(id=9, file_path=str(source), file_type="docx", filename="ad.docx")
    standard = SimpleNamespace(id=4, disease_id=2, name="AD标准", versions=[])
    versions = []

    class Query:
        def __init__(self, model): self.model = model
        def filter(self, *args, **kwargs): return self
        def first(self):
            name = getattr(self.model, "__name__", "")
            return {"Disease": disease, "Document": document, "ReferenceStandard": standard}.get(name)
        def all(self): return versions

    class Session:
        def query(self, model): return Query(model)
        def add(self, value):
            if value.__class__.__name__ == "ReferenceStandardVersion":
                value.id = len(versions) + 1
                versions.append(value)
                standard.versions.append(value)
        def commit(self): return None
        def refresh(self, value): return None

    db = Session()
    first = seed_standard_draft(db, 2, 9, "AD-2026-08-24")
    second = seed_standard_draft(db, 2, 9, "AD-2026-08-24")
    assert first.id == second.id
    assert first.status == "draft"


def test_seed_rejects_non_docx_document(tmp_path):
    source = tmp_path / "standard.pdf"
    source.write_bytes(b"pdf")
    document = SimpleNamespace(id=9, file_path=str(source), file_type="pdf", filename="standard.pdf")

    class Query:
        def __init__(self, model): self.model = model
        def filter(self, *args, **kwargs): return self
        def first(self):
            return SimpleNamespace(id=2) if getattr(self.model, "__name__", "") == "Disease" else document

    class Session:
        def query(self, model): return Query(model)

    try:
        seed_standard_draft(Session(), 2, 9, "bad")
    except ValueError as exc:
        assert "DOCX" in str(exc)
    else:
        raise AssertionError("expected non-DOCX validation")
