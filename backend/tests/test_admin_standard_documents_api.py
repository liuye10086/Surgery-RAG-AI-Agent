import hashlib
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError


# Importing app.api also imports the existing chat router, which constructs its
# client at import time.  This placeholder keeps this API-only test offline.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")


def _upload_file(filename: str, contents: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(contents))


class _Query:
    def __init__(self, first=None, rows=None):
        self.first_value = first
        self.rows = rows or []
        self.filters = []
        self.options_used = []
        self.ordering = []

    def options(self, *options):
        self.options_used.extend(options)
        return self

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def order_by(self, *ordering):
        self.ordering.extend(ordering)
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.rows


class _Db:
    def __init__(self, first=None, rows=None, commit_error=None):
        self.query_result = _Query(first=first, rows=rows)
        self.commit_error = commit_error
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def query(self, _model):
        return self.query_result

    def add(self, value):
        value.id = 1
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def refresh(self, _value):
        return None

    def rollback(self):
        self.rollbacks += 1


def _stored_file(path="stored.docx", content_hash="a" * 64):
    from app.services.standard_document_storage import StoredStandardFile

    return StoredStandardFile(path=path, file_type="docx", file_size=4, content_hash=content_hash)


def test_standard_document_router_exposes_admin_only_endpoints():
    from app.api.admin_standard_documents import router

    paths = {(route.path, next(iter(route.methods))) for route in router.routes}
    assert any(path == "/admin/standard-documents/upload" for path, _ in paths)
    assert any(path == "/admin/standard-documents" for path, _ in paths)
    assert any(path == "/admin/standard-documents/{document_id}" for path, _ in paths)


def test_standard_document_routes_all_require_admin():
    from app.api.admin_standard_documents import router
    from app.api.deps import require_admin

    for route in router.routes:
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


def test_standard_upload_rejects_non_docx_before_saving(monkeypatch):
    from app.services.standard_document_storage import save_standard_upload

    saved = []
    monkeypatch.setattr(
        "app.services.file_storage.save_upload",
        lambda file: saved.append(file) or "unused",
    )

    with pytest.raises(ValueError, match="DOCX"):
        save_standard_upload(_upload_file("standard.pdf", b"pdf"))

    assert saved == []


def test_standard_file_hash_is_sha256(tmp_path):
    from app.services.standard_document_storage import hash_standard_file

    path = tmp_path / "standard.docx"
    contents = b"standard document contents"
    path.write_bytes(contents)

    assert hash_standard_file(str(path)) == hashlib.sha256(contents).hexdigest()


def test_standard_document_out_derives_unlocked_state():
    from app.api.admin_standard_documents import standard_document_to_out

    output = standard_document_to_out(
        SimpleNamespace(
            id=1,
            title="AD标准",
            filename="ad.docx",
            file_path="x",
            file_type="docx",
            file_size=4,
            content_hash="a" * 64,
            uploaded_by=7,
            created_at=None,
            version=None,
        )
    )

    assert output.is_locked is False
    assert output.version_id is None
    assert "file_path" not in output.model_dump()


def test_upload_uses_filename_when_title_is_empty(monkeypatch):
    from app.api.admin_standard_documents import upload_standard_document

    db = _Db()
    monkeypatch.setattr(
        "app.api.admin_standard_documents.save_standard_upload",
        lambda file: _stored_file(),
    )

    result = upload_standard_document(
        file=_upload_file("ad.docx", b"docx"), title="   ", admin=SimpleNamespace(id=7), db=db
    )

    assert result.title == "ad.docx"
    assert result.file_type == "docx"
    assert result.uploaded_by == 7


def test_upload_removes_saved_file_for_duplicate_hash(monkeypatch):
    from app.api.admin_standard_documents import upload_standard_document

    deleted = []
    db = _Db(first=SimpleNamespace(id=11))
    monkeypatch.setattr(
        "app.api.admin_standard_documents.save_standard_upload",
        lambda file: _stored_file(path="duplicate.docx"),
    )
    monkeypatch.setattr(
        "app.api.admin_standard_documents.delete_standard_file",
        lambda path: deleted.append(path),
    )

    with pytest.raises(HTTPException) as exc_info:
        upload_standard_document(
            file=_upload_file("ad.docx", b"docx"), title=None, admin=SimpleNamespace(id=7), db=db
        )

    assert exc_info.value.status_code == 409
    assert deleted == ["duplicate.docx"]
    assert db.added == []


def test_upload_translates_integrity_race_and_removes_saved_file(monkeypatch):
    from app.api.admin_standard_documents import upload_standard_document

    deleted = []
    db = _Db(commit_error=IntegrityError("insert", {}, Exception("duplicate")))
    monkeypatch.setattr(
        "app.api.admin_standard_documents.save_standard_upload",
        lambda file: _stored_file(path="race.docx"),
    )
    monkeypatch.setattr(
        "app.api.admin_standard_documents.delete_standard_file",
        lambda path: deleted.append(path),
    )

    with pytest.raises(HTTPException) as exc_info:
        upload_standard_document(
            file=_upload_file("ad.docx", b"docx"), title=None, admin=SimpleNamespace(id=7), db=db
        )

    assert exc_info.value.status_code == 409
    assert db.rollbacks == 1
    assert deleted == ["race.docx"]


def test_upload_converts_extension_and_size_errors_to_http_errors(monkeypatch):
    from app.api.admin_standard_documents import upload_standard_document

    db = _Db()
    monkeypatch.setattr(
        "app.api.admin_standard_documents.save_standard_upload",
        lambda file: (_ for _ in ()).throw(ValueError("标准源文件只支持 DOCX")),
    )
    with pytest.raises(HTTPException) as extension_error:
        upload_standard_document(
            file=_upload_file("ad.docx", b"docx"), title=None, admin=SimpleNamespace(id=7), db=db
        )
    assert extension_error.value.status_code == 422

    monkeypatch.setattr(
        "app.api.admin_standard_documents.save_standard_upload",
        lambda file: (_ for _ in ()).throw(ValueError("文件大小超过限制: 50 MB")),
    )
    with pytest.raises(HTTPException) as size_error:
        upload_standard_document(
            file=_upload_file("ad.docx", b"docx"), title=None, admin=SimpleNamespace(id=7), db=db
        )
    assert size_error.value.status_code == 400


def test_list_available_only_filters_unlinked_documents_and_eager_loads_relationships():
    from app.api.admin_standard_documents import list_standard_documents

    document = SimpleNamespace(
        id=1, title="AD", filename="ad.docx", file_type="docx", file_size=4,
        content_hash="a" * 64, uploaded_by=1, created_at=None, version=None,
    )
    db = _Db(rows=[document])

    result = list_standard_documents(available_only=True, admin=SimpleNamespace(id=7), db=db)

    assert [item.id for item in result] == [1]
    assert db.query_result.options_used
    assert db.query_result.filters
    assert db.query_result.ordering


def test_delete_linked_standard_document_returns_conflict():
    from app.api.admin_standard_documents import delete_standard_document

    db = _Db(first=SimpleNamespace(version=SimpleNamespace(id=4), file_path="linked.docx"))

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 409
    assert db.deleted == []


def test_delete_rolls_back_when_strict_disk_deletion_fails(monkeypatch):
    from app.api.admin_standard_documents import delete_standard_document

    document = SimpleNamespace(version=None, file_path="cannot-delete.docx")
    db = _Db(first=document)
    monkeypatch.setattr(
        "app.api.admin_standard_documents.delete_standard_file",
        lambda path: (_ for _ in ()).throw(OSError("locked")),
    )

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 500
    assert db.deleted == [document]
    assert db.flushes == 1
    assert db.commits == 0
    assert db.rollbacks == 1


def test_delete_unlinked_standard_document_removes_disk_file_then_commits(monkeypatch):
    from app.api.admin_standard_documents import delete_standard_document

    deleted_paths = []
    document = SimpleNamespace(version=None, file_path="available.docx")
    db = _Db(first=document)
    monkeypatch.setattr(
        "app.api.admin_standard_documents.delete_standard_file",
        lambda path: deleted_paths.append(path),
    )

    assert delete_standard_document(1, admin=SimpleNamespace(id=7), db=db) is None
    assert db.deleted == [document]
    assert db.flushes == 1
    assert deleted_paths == ["available.docx"]
    assert db.commits == 1
