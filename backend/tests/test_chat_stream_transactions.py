import asyncio
import json
import os

import pytest
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
