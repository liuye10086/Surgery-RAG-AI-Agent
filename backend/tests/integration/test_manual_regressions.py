"""Manual acceptance regressions against the explicitly configured local test DB."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Chunk, Document, Message, ReferenceStandard, ReferenceStandardVersion,
    Session as ChatSession, StandardChangeLog, StandardDocument,
    StandardParseCandidate, StandardRule, StandardSegment, User,
)


@pytest.fixture
def admin(db, client):
    user = User(username="manual-admin", email="admin@example.com", hashed_password="disabled", role="admin")
    db.add(user)
    db.commit()
    return client(user.id)


@pytest.fixture
def candidate(db, admin):
    standard = ReferenceStandard(disease_id=1, name="Synthetic regression standard")
    document = StandardDocument(title="Synthetic fixture", filename="fixture.docx", file_path="unused.docx", file_type="docx", file_size=1, content_hash="a" * 64)
    db.add_all([standard, document])
    db.flush()
    version = ReferenceStandardVersion(standard_id=standard.id, standard_document_id=document.id, version_label="regression", content_hash=document.content_hash, parser_version="v1", status="draft")
    db.add(version)
    db.flush()
    segment = StandardSegment(version_id=version.id, raw_text="Synthetic software fixture; no clinical use", segment_type="paragraph")
    db.add(segment)
    db.flush()
    item = StandardParseCandidate(version_id=version.id, segment_id=segment.id, source_type="manual_test", parser_version="v1", status="accepted", candidate_json={"rule_type": "qualitative_direction", "interpretation": "Synthetic fixture"})
    db.add(item)
    db.commit()
    return item


def test_materialized_candidate_cannot_be_reopened(db, admin, candidate):
    path = f"/api/v1/admin/reference-standard-candidates/{candidate.id}"
    response = admin.post(path + "/materialize", params={"reason": "Synthetic review"})
    assert response.status_code == 200
    rule_id = response.json()["id"]
    for target in ("accepted", "pending", "rejected", "failed"):
        assert admin.patch(path, json={"status": target}).status_code == 409
    assert admin.post(path + "/materialize", params={"reason": "Repeat"}).status_code == 409
    db.expire_all()
    assert db.get(StandardParseCandidate, candidate.id).status == "materialized"
    rules = db.query(StandardRule).filter_by(version_id=candidate.version_id).all()
    assert [r.id for r in rules] == [rule_id]
    audit = db.query(StandardChangeLog).filter_by(version_id=candidate.version_id).one()
    assert audit.action == "materialize_candidate"
    assert audit.entity_id == rule_id
    assert audit.after_json["candidate_id"] == candidate.id


@pytest.mark.parametrize("version_status", ["approved", "retired"])
def test_review_candidate_rejects_immutable_version(db, admin, candidate, version_status):
    version = db.get(ReferenceStandardVersion, candidate.version_id)
    version.status = version_status
    db.commit()
    response = admin.patch(f"/api/v1/admin/reference-standard-candidates/{candidate.id}", json={"status": "rejected"})
    assert response.status_code == 409
    db.expire_all()
    assert db.get(StandardParseCandidate, candidate.id).status == "accepted"


def test_review_candidate_valid_transitions_and_permissions(db, client, admin, candidate):
    path = f"/api/v1/admin/reference-standard-candidates/{candidate.id}"
    assert client(1).patch(path, json={"status": "rejected"}).status_code == 403
    for target in ("pending", "rejected", "failed", "accepted"):
        assert admin.patch(path, json={"status": target}).json()["status"] == target
        db.expire_all()
        assert db.get(StandardParseCandidate, candidate.id).status == target
    assert admin.patch(path, json={"status": "materialized"}).status_code == 422


def test_concurrent_review_and_materialize_keep_one_rule(db, integration_engine, candidate):
    from fastapi import HTTPException
    from app.api.admin_standards import review_candidate
    from app.services.standard_lifecycle import materialize_candidate

    factory = sessionmaker(bind=integration_engine)
    barrier = Barrier(2)
    cid, vid = candidate.id, candidate.version_id

    def execute(action):
        with factory() as session:
            barrier.wait(5)
            if action == "review":
                try:
                    review_candidate(cid, {"status": "accepted"}, admin=None, db=session)
                except HTTPException as exc:
                    assert exc.status_code == 409
            else:
                materialize_candidate(session, candidate_id=cid, admin_id=1, reason="Synthetic concurrency test")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, action) for action in ("review", "materialize")]
        for future in futures:
            future.result(timeout=15)
    db.expire_all()
    assert db.get(StandardParseCandidate, cid).status == "materialized"
    assert db.query(StandardRule).filter_by(version_id=vid).count() == 1
    assert db.query(StandardChangeLog).filter_by(version_id=vid).count() == 1


def test_review_refreshes_candidate_read_before_materialization(db, integration_engine, candidate):
    from fastapi import HTTPException
    from app.api.admin_standards import review_candidate
    from app.services.standard_lifecycle import materialize_candidate

    factory = sessionmaker(bind=integration_engine)
    probe_read, resume_review = Event(), Event()
    cid, vid = candidate.id, candidate.version_id

    def review():
        with factory() as session:
            def pause_after_probe(conn, cursor, statement, params, context, many):
                if "FROM standard_parse_candidates" in statement and not probe_read.is_set():
                    probe_read.set()
                    assert resume_review.wait(10)

            event.listen(session.connection(), "after_cursor_execute", pause_after_probe)
            with pytest.raises(HTTPException) as caught:
                review_candidate(cid, {"status": "accepted"}, admin=None, db=session)
            assert caught.value.status_code == 409

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending_review = pool.submit(review)
        try:
            assert probe_read.wait(10)
            with factory() as session:
                materialize_candidate(session, candidate_id=cid, admin_id=1, reason="Synthetic interleaving test")
        finally:
            resume_review.set()
        pending_review.result(timeout=15)
    db.expire_all()
    assert db.get(StandardParseCandidate, cid).status == "materialized"
    assert db.query(StandardRule).filter_by(version_id=vid).count() == 1
    assert db.query(StandardChangeLog).filter_by(version_id=vid).count() == 1


def test_fulltext_title_uses_current_document_after_rename_and_clear(db, admin, integration_engine):
    import json
    from app.core.config import settings
    from app.rag.pipeline import _fulltext_search

    doc = Document(title="OLDTOKEN", filename="FALLBACKTOKEN", status="indexed", access_scope="both")
    db.add(doc)
    db.flush()
    chunk = Chunk(document_id=doc.id, content="zzzz", chunk_index=0, generation=1, is_current=True)
    db.add(chunk)
    db.commit()
    # Real pg_trgm SQL over connection-local vector metadata; no model invocation.
    from sqlalchemy.orm import Session
    with integration_engine.connect() as connection, Session(bind=connection) as search_db:
        search_db.execute(text("CREATE TEMP TABLE langchain_pg_collection (uuid text, name text)"))
        search_db.execute(text("CREATE TEMP TABLE langchain_pg_embedding (collection_id text, document text, cmetadata jsonb)"))
        search_db.execute(text("INSERT INTO langchain_pg_collection VALUES ('test', :name)"), {"name": settings.VECTOR_COLLECTION_NAME})
        search_db.execute(text("INSERT INTO langchain_pg_embedding VALUES ('test', 'zzzz', CAST(:metadata AS jsonb))"), {"metadata": json.dumps({"chunk_id": chunk.id, "document_title": "OLDTOKEN"})})
        assert admin.put(f"/api/v1/admin/documents/{doc.id}", json={"title": "NEWTOKEN"}).status_code == 200
        matches = _fulltext_search(search_db, "NEWTOKEN", 5, access_scope="chat")
        assert [item.chunk.id for item in matches] == [chunk.id]
        assert matches[0].fulltext_score == 1.0
        assert all(item.fulltext_score < 1.0 for item in _fulltext_search(search_db, "OLDTOKEN", 5, access_scope="chat"))
        assert admin.put(f"/api/v1/admin/documents/{doc.id}", json={"title": None}).status_code == 200
        matches = _fulltext_search(search_db, "FALLBACKTOKEN", 5, access_scope="operator")
        assert [item.chunk.id for item in matches] == [chunk.id]
        assert matches[0].fulltext_score == 1.0


@pytest.mark.parametrize("scope", ["chat", "operator", "both"])
def test_source_scope_matrix(db, client, admin, tmp_path, monkeypatch, scope):
    from app.core.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    doc = Document(title="Synthetic " + scope, filename="fixture.png", file_type=".png", status="indexed", access_scope=scope, active_generation=1)
    db.add(doc)
    db.flush()
    db.add(Chunk(document_id=doc.id, content="Synthetic source body", chunk_index=0, generation=1, is_current=True))
    reader = User(username="reader", email="reader@example.com", hashed_password="disabled", role="user")
    outsider = User(username="outsider", email="outsider@example.com", hashed_password="disabled", role="user")
    db.add_all([reader, outsider])
    db.flush()
    chat = ChatSession(user_id=reader.id, title="Synthetic citation")
    db.add(chat)
    db.flush()
    image_url = f"/api/v1/files/images/{doc.id}/1/test.png"
    db.add(Message(session_id=chat.id, role="assistant", content="Synthetic", sources=[{"document_id": doc.id, "images": [{"url": image_url}]}]))
    image = tmp_path / "images" / str(doc.id) / "1" / "test.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    db.commit()
    for actor, expected in ((client(1), 403 if scope == "chat" else 200), (client(reader.id), 403 if scope == "operator" else 200), (client(outsider.id), 403), (admin, 200)):
        response = actor.get(f"/api/v1/documents/{doc.id}/content")
        assert response.status_code == expected
        if expected == 200:
            assert "Synthetic source body" in response.text
        response = actor.get(image_url)
        assert response.status_code == expected
        if expected == 200:
            assert response.content == image.read_bytes()


def test_broken_pdf_returns_and_persists_safe_error(db, admin, tmp_path):
    path = tmp_path / "private-broken.pdf"
    path.write_bytes(b"Synthetic invalid PDF")
    doc = Document(title="Synthetic bad PDF", filename=path.name, file_path=str(path), file_type=".pdf", file_size=path.stat().st_size)
    db.add(doc)
    db.commit()
    response = admin.post(f"/api/v1/admin/documents/{doc.id}/chunk")
    assert response.status_code == 500
    assert response.json()["detail"] == "分块失败，请检查文件是否损坏或格式是否受支持"
    db.expire_all()
    saved = db.get(Document, doc.id)
    assert saved.status == "failed"
    assert saved.error_message == response.json()["detail"]
    assert db.query(Chunk).filter_by(document_id=doc.id).count() == 0


def test_title_update_is_partial_and_persisted(db, client, admin):
    doc = Document(title="Old title", filename="fixture.pdf", status="indexed", access_scope="operator")
    db.add(doc)
    db.commit()
    path = f"/api/v1/admin/documents/{doc.id}"
    assert client(1).put(path, json={"title": "forbidden"}).status_code == 403
    response = admin.put(path, json={"title": " 新标题 "})
    assert response.status_code == 200
    assert response.json()["title"] == "新标题"
    db.expire_all()
    saved = db.get(Document, doc.id)
    assert (saved.title, saved.filename, saved.status, saved.access_scope) == ("新标题", "fixture.pdf", "indexed", "operator")
    assert admin.put(path, json={"access_scope": "both"}).json()["title"] == "新标题"
    assert admin.put(path, json={"title": "字" * 501}).status_code == 422
    assert admin.get(path).json()["title"] == "新标题"
    for title in (" ", None):
        assert admin.put(path, json={"title": title}).json()["title"] is None


@pytest.mark.parametrize("values", [{"username": ""}, {"username": " \t"}, {"password": ""}, {"password": "x"}])
def test_invalid_registration_does_not_create_user(db, admin, values):
    payload = {"username": "regression-user", "email": "regression@example.com", "password": "123456", **values}
    count = db.query(User).count()
    assert admin.post("/api/v1/auth/register", json=payload).status_code == 422
    assert db.query(User).count() == count


def test_valid_registration_and_login(db, admin):
    response = admin.post("/api/v1/auth/register", json={"username": " valid-user ", "email": "valid@example.com", "password": "123456"})
    assert response.status_code == 200
    assert db.query(User).filter_by(username="valid-user").one().role == "user"
    assert admin.post("/api/v1/auth/login/json", json={"username": "valid-user", "password": "123456"}).status_code == 200
