import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.standard_lifecycle import seed_standard_draft


def _seed_script_module():
    path = Path(__file__).parents[2] / "scripts" / "seed_standard_drafts.py"
    spec = importlib.util.spec_from_file_location("seed_standard_drafts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_seed_script_uses_standard_documents_not_knowledge_documents():
    project_root = Path(__file__).parents[2]
    source = project_root.joinpath("scripts/seed_standard_drafts.py").read_text(
        encoding="utf-8"
    )

    assert "from app.db.models import StandardDocument" in source
    assert "from app.db.models import Document" not in source
    assert "access_scope" not in source
    assert not project_root.joinpath("scripts/upload_standards.py").exists()


def test_standard_document_rejects_non_docx_and_missing_paths(tmp_path):
    script = _seed_script_module()
    non_docx = tmp_path / "standard.pdf"
    non_docx.write_bytes(b"pdf")

    with pytest.raises(ValueError, match="DOCX"):
        script._standard_document(SimpleNamespace(), non_docx, admin_id=7)
    with pytest.raises(ValueError, match="不存在"):
        script._standard_document(SimpleNamespace(), tmp_path / "missing.docx", admin_id=7)


def test_standard_document_reuses_matching_content_hash(tmp_path, monkeypatch):
    script = _seed_script_module()
    source = tmp_path / "ad.docx"
    source.write_bytes(b"docx-content")
    existing = SimpleNamespace(id=9, content_hash="a" * 64)
    hash_calls = []

    class Query:
        def filter(self, *conditions):
            return self

        def first(self):
            return existing

    class Session:
        def query(self, model):
            assert model is script.StandardDocument
            return Query()

        def add(self, value):
            raise AssertionError("existing content must not create another row")

        def commit(self):
            raise AssertionError("existing content must not commit")

    def fake_hash(path):
        hash_calls.append(path)
        return existing.content_hash

    monkeypatch.setattr(script, "hash_standard_file", fake_hash)

    assert script._standard_document(Session(), source, admin_id=7) is existing
    assert hash_calls == [str(source)]


def test_standard_document_records_uploading_admin(tmp_path, monkeypatch):
    script = _seed_script_module()
    source = tmp_path / "fatty-liver.docx"
    source.write_bytes(b"docx-content")
    added = []

    class Query:
        def filter(self, *conditions):
            return self

        def first(self):
            return None

    class Session:
        def query(self, model):
            assert model is script.StandardDocument
            return Query()

        def add(self, value):
            added.append(value)

        def commit(self):
            return None

        def refresh(self, value):
            return None

    monkeypatch.setattr(script, "hash_standard_file", lambda path: "b" * 64)

    result = script._standard_document(Session(), source, admin_id=23)

    assert result is added[0]
    assert result.content_hash == "b" * 64
    assert result.uploaded_by == 23


def test_seed_draft_is_idempotent_for_same_standard_document(tmp_path):
    source = tmp_path / "ad.docx"
    source.write_bytes(b"docx-content")
    disease = SimpleNamespace(id=2, name="AD")
    document = SimpleNamespace(
        id=9,
        file_path=str(source),
        file_type=".docx",
        filename="ad.docx",
        content_hash="a" * 64,
        version=None,
    )
    standard = SimpleNamespace(id=4, disease_id=2, name="AD标准", versions=[])
    versions = []

    class Query:
        def __init__(self, model): self.model = model
        def filter(self, *args, **kwargs): return self
        def with_for_update(self): return self
        def first(self):
            name = getattr(self.model, "__name__", "")
            return {
                "Disease": disease,
                "StandardDocument": document,
                "ReferenceStandard": standard,
            }.get(name)
        def all(self): return versions

    class Session:
        def query(self, model): return Query(model)
        def add(self, value):
            if value.__class__.__name__ == "ReferenceStandardVersion":
                value.id = len(versions) + 1
                versions.append(value)
                standard.versions.append(value)
                document.version = value
                value.__dict__["standard"] = standard
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
        def with_for_update(self): return self
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
