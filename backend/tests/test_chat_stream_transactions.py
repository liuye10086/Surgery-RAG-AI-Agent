import asyncio
import json
import os

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import JSON, MetaData, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from app.api import chat
from app.db.models import AuditLog, Message, Session as ChatSession, User
from app.schemas.chat import AskRequest


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'chat.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    metadata = MetaData()
    for model in (User, ChatSession, Message, AuditLog):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    monkeypatch.setattr(
        chat, "build_full_chain",
        lambda retriever: RunnableLambda(lambda values: AIMessage(content="合成回答已完成")),
    )
    with Session(engine, expire_on_commit=False) as db:
        db.add(User(id=1, username="synthetic", email="synthetic@test.invalid", hashed_password="x"))
        db.add(ChatSession(id=1, user_id=1, title="既有标题"))
        db.commit()
        yield db
    engine.dispose()


async def _consume(db, *, retry_id=None, before_stream=None):
    response = await chat.ask(
        1, AskRequest(content="合成测试问题", retry_message_id=retry_id, client_request_id="synthetic-request"),
        db=db, current_user=db.get(User, 1),
    )
    if before_stream:
        before_stream()
    return "".join([part async for part in response.body_iterator])


@pytest.mark.parametrize("retry", [False, True])
def test_audit_failure_does_not_undo_successful_answer(chat_db, retry):
    db = chat_db
    retry_id = None
    if retry:
        db.add(Message(id=10, session_id=1, role="user", content="合成测试问题"))
        db.add(Message(id=11, session_id=1, role="assistant", content="旧错误", is_error=True))
        db.commit()
        retry_id = 11
    db.execute(text("CREATE TRIGGER reject_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(FAIL, 'synthetic audit failure'); END"))
    db.commit()

    stream = asyncio.run(_consume(db, retry_id=retry_id))

    assert "event: done" in stream
    assert "event: error" not in stream
    db.close()
    with Session(db.bind) as verify:
        answers = verify.query(Message).filter_by(role="assistant").all()
        assert len(answers) == 1
        assert answers[0].content == "合成回答已完成"
        assert answers[0].is_error is False
        if retry:
            assert answers[0].id == retry_id
        assert verify.query(AuditLog).count() == 0


def test_answer_commit_failure_emits_error_instead_of_done(chat_db):
    db = chat_db

    def fail_next_commit():
        def reject_once(session):
            if session.info.pop("reject_answer_commit", False):
                raise RuntimeError("synthetic answer commit failure")
        db.info["reject_answer_commit"] = True
        event.listen(db, "before_commit", reject_once)

    stream = asyncio.run(_consume(db, before_stream=fail_next_commit))

    assert "event: error" in stream
    assert "event: done" not in stream
    error = next(part for part in stream.split("\n\n") if part.startswith("event: error"))
    payload = json.loads(error.split("data: ", 1)[1])
    assert db.get(Message, payload["user_message_id"]).role == "user"
    answers = db.query(Message).filter_by(role="assistant").all()
    assert len(answers) == 1
    assert answers[0].is_error is True


def test_successful_answer_and_audit_are_saved(chat_db):
    stream = asyncio.run(_consume(chat_db))
    assert "event: done" in stream
    done = next(part for part in stream.split("\n\n") if part.startswith("event: done"))
    payload = json.loads(done.split("data: ", 1)[1])
    chat_db.close()
    with Session(chat_db.bind) as verify:
        assert verify.get(Message, payload["message_id"]).content == "合成回答已完成"
        assert verify.get(Message, payload["user_message_id"]).role == "user"
        assert verify.query(AuditLog).count() == 1


@pytest.mark.parametrize("entry", ["get_session", "delete_session", "ask"])
@pytest.mark.parametrize("session_id", [2, 999])
def test_session_entries_reject_other_or_missing_session(chat_db, monkeypatch, entry, session_id):
    db = chat_db
    db.add(User(id=2, username="other", email="other@test.invalid", hashed_password="x"))
    db.add(ChatSession(id=2, user_id=2, title="他人会话"))
    db.commit()
    user = db.get(User, 1)
    queries = []
    query = db.query

    def record_query(model):
        queries.append(model)
        return query(model)

    def unexpected_filter(content):
        pytest.fail("会话归属检查必须先于输入过滤")

    monkeypatch.setattr(db, "query", record_query)
    monkeypatch.setattr(chat, "filter_input", unexpected_filter)
    with pytest.raises(HTTPException) as exc:
        if entry == "ask":
            asyncio.run(chat.ask(session_id, AskRequest(content="合成测试问题"), db=db, current_user=user))
        else:
            getattr(chat, entry)(session_id, db=db, current_user=user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Session not found"
    assert queries == [ChatSession]
    with Session(db.bind) as verify:
        assert verify.get(ChatSession, 1).user_id == 1
        assert verify.get(ChatSession, 2).user_id == 2
        assert verify.query(Message).count() == 0


@pytest.mark.parametrize("entry", ["get_session", "delete_session", "ask"])
def test_session_entries_accept_owner(chat_db, entry):
    db = chat_db
    user = db.get(User, 1)
    if entry == "get_session":
        session = chat.get_session(1, db=db, current_user=user)
        assert (session.id, session.user_id, session.title) == (1, 1, "既有标题")
    elif entry == "delete_session":
        assert chat.delete_session(1, db=db, current_user=user) is None
        with Session(db.bind) as verify:
            assert verify.get(ChatSession, 1) is None
    else:
        stream = asyncio.run(_consume(db))
        events = [part.split("\n", 1)[0] for part in stream.split("\n\n") if part]
        assert events == ["event: stage", "event: delta", "event: sources", "event: done"]
        payload = json.loads(stream.split("event: done\ndata: ", 1)[1])
        with Session(db.bind) as verify:
            assert verify.get(Message, payload["message_id"]).session_id == 1
            assert verify.get(Message, payload["user_message_id"]).session_id == 1


@pytest.mark.parametrize("failure", ["ordinary", "retry_existing", "retry_missing", "history_init"])
def test_error_message_fields_ids_and_transaction_order(chat_db, monkeypatch, failure):
    db = chat_db
    db.get(ChatSession, 1).title = "新会话"
    retry_id = None
    if failure in ("retry_existing", "history_init"):
        retry_id = 11
        db.add(Message(id=10, session_id=1, role="user", content="合成测试问题"))
        db.add(Message(
            id=11, session_id=1, role="assistant", content="旧错误",
            sources=[{"synthetic": "old-source"}], is_error=False,
            is_no_knowledge=True, lc_message={"synthetic": "old-message"},
            client_request_id="old-assistant-request",
        ))
    elif failure == "retry_missing":
        retry_id = 999
    db.commit()

    async def synthetic_title(question):
        return "合成标题"

    def fail_generation(*args, **kwargs):
        raise RuntimeError("synthetic generation failure")

    monkeypatch.setattr(chat, "_generate_title", synthetic_title)
    monkeypatch.setattr(
        chat, "SurgeryChatMessageHistory" if failure == "history_init" else "build_full_chain",
        fail_generation,
    )
    operations = []

    def before_stream():
        for name in ("rollback", "add", "commit", "refresh", "query"):
            original = getattr(db, name)

            def record(*args, _name=name, _original=original, **kwargs):
                operations.append((_name, args[0] if _name == "query" else None))
                return _original(*args, **kwargs)

            monkeypatch.setattr(db, name, record)

    stream = asyncio.run(_consume(db, retry_id=retry_id, before_stream=before_stream))
    events = [part for part in stream.split("\n\n") if part]
    assert len(events) == 1
    assert events[0].startswith("event: error\ndata: ")
    payload = json.loads(events[0].split("data: ", 1)[1])
    assert payload["detail"] == "synthetic generation failure"
    assert payload["title"] == "合成标题"
    expected_operations = [("rollback", None)]
    if failure in ("retry_existing", "retry_missing"):
        expected_operations.append(("query", Message))
    if failure != "retry_existing":
        expected_operations.append(("add", None))
    expected_operations.append(("commit", None))
    if failure != "retry_existing":
        expected_operations.append(("refresh", None))
    expected_operations.extend([("query", ChatSession), ("commit", None)])
    assert operations == expected_operations

    with Session(db.bind) as verify:
        error = verify.get(Message, payload["message_id"])
        assert error is not None
        assert (error.session_id, error.role, error.content, error.sources, error.is_error) == (
            1, "assistant", "生成失败：synthetic generation failure", [], True,
        )
        assert verify.get(ChatSession, 1).title == "合成标题"
        assert verify.query(AuditLog).count() == 0
        if failure == "ordinary":
            user = verify.get(Message, payload["user_message_id"])
            assert (user.session_id, user.role, user.content, user.client_request_id) == (
                1, "user", "合成测试问题", "synthetic-request",
            )
        else:
            assert payload["user_message_id"] is None
        if failure == "retry_existing":
            assert error.id == 11
            assert error.is_no_knowledge is True
            assert error.lc_message == {"synthetic": "old-message"}
            assert error.client_request_id == "old-assistant-request"
        else:
            assert error.id != retry_id
            assert error.is_no_knowledge is False
            assert error.lc_message is None
            assert error.client_request_id is None
        if failure == "history_init":
            old = verify.get(Message, 11)
            assert (old.content, old.sources, old.is_error) == (
                "旧错误", [{"synthetic": "old-source"}], False,
            )
        assert verify.query(Message).filter_by(role="assistant").count() == (2 if failure == "history_init" else 1)
