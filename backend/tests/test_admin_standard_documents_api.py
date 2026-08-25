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
        self.events = []

    def options(self, *options):
        self.options_used.extend(options)
        return self

    def filter(self, *conditions):
        self.events.append("filter")
        self.filters.extend(conditions)
        return self

    def with_for_update(self):
        self.events.append("with_for_update")
        return self

    def order_by(self, *ordering):
        self.ordering.extend(ordering)
        return self

    def first(self):
        self.events.append("first")
        return self.first_value

    def all(self):
        return self.rows


class _Db:
    def __init__(
        self,
        first=None,
        rows=None,
        commit_error=None,
        refresh_error=None,
        flush_error=None,
    ):
        self.query_result = _Query(first=first, rows=rows)
        self.commit_error = commit_error
        self.refresh_error = refresh_error
        self.flush_error = flush_error
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
        if self.flush_error:
            raise self.flush_error

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def refresh(self, _value):
        if self.refresh_error:
            raise self.refresh_error
        return None

    def rollback(self):
        self.rollbacks += 1


class _TransactionalDeleteDb(_Db):
    def __init__(self, document, commit_error=None):
        super().__init__(first=document, commit_error=commit_error)
        self.records = [document]
        self.delete_attempts = []
        self.pending_deletes = []

    def delete(self, value):
        self.delete_attempts.append(value)
        self.pending_deletes.append(value)

    def commit(self):
        super().commit()
        for value in self.pending_deletes:
            self.records.remove(value)
        self.pending_deletes.clear()

    def rollback(self):
        super().rollback()
        self.pending_deletes.clear()


def _stored_file(path="stored.docx", content_hash="a" * 64):
    from app.services.standard_document_storage import StoredStandardFile

    return StoredStandardFile(path=path, file_type="docx", file_size=4, content_hash=content_hash)


def _integrity_error(constraint_name):
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint_name))
    return IntegrityError("delete", {}, orig)


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


def test_standard_upload_removes_saved_file_when_size_lookup_fails(monkeypatch, tmp_path):
    from app.services.standard_document_storage import save_standard_upload

    source = tmp_path / "size-failure.docx"
    source.write_bytes(b"saved upload")
    monkeypatch.setattr(
        "app.services.standard_document_storage.file_storage.save_upload",
        lambda _file: str(source),
    )
    monkeypatch.setattr(
        "app.services.standard_document_storage.file_storage.get_file_size",
        lambda _path: (_ for _ in ()).throw(OSError("size failed")),
    )

    with pytest.raises(OSError, match="size failed"):
        save_standard_upload(_upload_file("standard.docx", b"docx"))

    assert not source.exists()


def test_standard_upload_removes_saved_file_when_hashing_fails(monkeypatch, tmp_path):
    from app.services.standard_document_storage import save_standard_upload

    source = tmp_path / "hash-failure.docx"
    source.write_bytes(b"saved upload")
    monkeypatch.setattr(
        "app.services.standard_document_storage.file_storage.save_upload",
        lambda _file: str(source),
    )
    monkeypatch.setattr(
        "app.services.standard_document_storage.hash_standard_file",
        lambda _path: (_ for _ in ()).throw(OSError("hash failed")),
    )

    with pytest.raises(OSError, match="hash failed"):
        save_standard_upload(_upload_file("standard.docx", b"docx"))

    assert not source.exists()


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
    db = _Db(flush_error=IntegrityError("insert", {}, Exception("duplicate")))
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
    assert db.commits == 0
    assert deleted == ["race.docx"]


def test_upload_refresh_failure_rolls_back_before_commit_and_removes_saved_file(monkeypatch):
    from app.api.admin_standard_documents import upload_standard_document

    deleted = []
    db = _Db(refresh_error=RuntimeError("refresh failed"))
    monkeypatch.setattr(
        "app.api.admin_standard_documents.save_standard_upload",
        lambda file: _stored_file(path="refresh-failure.docx"),
    )
    monkeypatch.setattr(
        "app.api.admin_standard_documents.delete_standard_file",
        lambda path: deleted.append(path),
    )

    with pytest.raises(HTTPException) as exc_info:
        upload_standard_document(
            file=_upload_file("ad.docx", b"docx"), title=None, admin=SimpleNamespace(id=7), db=db
        )

    assert exc_info.value.status_code == 500
    assert db.flushes == 1
    assert db.commits == 0
    assert db.rollbacks == 1
    assert deleted == ["refresh-failure.docx"]


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


def test_delete_standard_document_locks_parent_before_link_check():
    from app.api.admin_standard_documents import delete_standard_document

    document = SimpleNamespace(version=SimpleNamespace(id=4), file_path="linked.docx")
    db = _Db(first=document)

    with pytest.raises(HTTPException):
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert db.query_result.events[:3] == ["filter", "with_for_update", "first"]


def test_delete_document_fk_race_at_flush_maps_named_constraint_to_conflict(tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    source = tmp_path / "linked-during-delete.docx"
    source.write_bytes(b"standard contents")
    document = SimpleNamespace(version=None, file_path=str(source))
    db = _Db(
        first=document,
        flush_error=_integrity_error("fk_reference_standard_versions_standard_document"),
    )

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "标准文件已关联版本，不可删除"
    assert db.rollbacks == 1
    assert source.read_bytes() == b"standard contents"


def test_delete_document_unrelated_integrity_error_remains_server_error(tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    source = tmp_path / "unrelated-error.docx"
    source.write_bytes(b"standard contents")
    document = SimpleNamespace(version=None, file_path=str(source))
    db = _Db(first=document, flush_error=_integrity_error("some_other_constraint"))

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "标准文件删除失败"


def test_delete_document_fk_race_at_commit_restores_file_and_returns_conflict(tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    contents = b"standard contents"
    source = tmp_path / "commit-race.docx"
    source.write_bytes(contents)
    document = SimpleNamespace(version=None, file_path=str(source))
    db = _TransactionalDeleteDb(
        document,
        commit_error=_integrity_error("fk_reference_standard_versions_standard_document"),
    )

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "标准文件已关联版本，不可删除"
    assert db.rollbacks == 1
    assert db.records == [document]
    assert source.read_bytes() == contents


def test_delete_unlink_failure_rolls_back_and_preserves_original_bytes(monkeypatch, tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    contents = b"standard contents"
    source = tmp_path / "cannot-delete.docx"
    source.write_bytes(contents)
    document = SimpleNamespace(version=None, file_path=str(source))
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
    assert source.read_bytes() == contents
    assert list(tmp_path.iterdir()) == [source]


def test_delete_missing_standard_file_rolls_back_database_delete(tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    document = SimpleNamespace(version=None, file_path=str(tmp_path / "missing.docx"))
    db = _TransactionalDeleteDb(document)

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 500
    assert db.delete_attempts == [document]
    assert db.commits == 0
    assert db.rollbacks == 1
    assert db.records == [document]


def test_delete_commit_failure_rolls_back_and_restores_original_file(tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    contents = b"original standard document bytes"
    source = tmp_path / "available.docx"
    source.write_bytes(contents)
    document = SimpleNamespace(version=None, file_path=str(source))
    db = _TransactionalDeleteDb(document, commit_error=RuntimeError("commit failed"))

    with pytest.raises(HTTPException) as exc_info:
        delete_standard_document(1, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 500
    assert db.delete_attempts == [document]
    assert db.commits == 1
    assert db.rollbacks == 1
    assert db.records == [document]
    assert source.read_bytes() == contents
    assert list(tmp_path.iterdir()) == [source]


def test_delete_unlinked_standard_document_removes_disk_file_before_commit(monkeypatch, tmp_path):
    from app.api.admin_standard_documents import delete_standard_document

    events = []
    source = tmp_path / "available.docx"
    source.write_bytes(b"standard contents")
    document = SimpleNamespace(version=None, file_path=str(source))

    class OrderedDb(_Db):
        def commit(self):
            events.append("commit")
            super().commit()

    db = OrderedDb(first=document)

    def unlink(path):
        events.append("unlink")
        Path(path).unlink()

    monkeypatch.setattr(
        "app.api.admin_standard_documents.delete_standard_file",
        unlink,
    )

    assert delete_standard_document(1, admin=SimpleNamespace(id=7), db=db) is None
    assert db.deleted == [document]
    assert db.flushes == 1
    assert db.commits == 1
    assert events == ["unlink", "commit"]
    assert not source.exists()
    assert list(tmp_path.iterdir()) == []
