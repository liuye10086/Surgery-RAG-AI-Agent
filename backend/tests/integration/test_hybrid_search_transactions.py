from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.rag import pipeline


@pytest.mark.parametrize("failed_branch", ["vector", "fulltext"])
def test_sql_failure_isolated_from_other_branch_and_callers_writes(db, monkeypatch, failed_branch):
    db.execute(text("CREATE TEMP TABLE rag_caller_write (id integer) ON COMMIT DROP"))
    db.execute(text("INSERT INTO rag_caller_write VALUES (42)"))
    surviving = pipeline.RetrievedChunk(chunk=SimpleNamespace(id=81), score=1.0)

    def failing(session, *args, **kwargs):
        session.execute(text("SELECT 1 / 0"))

    def succeeding(session, *args, **kwargs):
        assert session.execute(text("SELECT id FROM rag_caller_write")).scalar_one() == 42
        return [surviving]

    monkeypatch.setattr(pipeline, "_vector_search", failing if failed_branch == "vector" else succeeding)
    monkeypatch.setattr(pipeline, "_fulltext_search", failing if failed_branch == "fulltext" else succeeding)

    results = pipeline.hybrid_search(db, "synthetic query")

    assert [result.chunk.id for result in results] == [81]
    assert db.execute(text("SELECT id FROM rag_caller_write")).scalar_one() == 42
    db.rollback()


def test_both_sql_failures_leave_outer_transaction_usable(db, monkeypatch):
    def failing(session, *args, **kwargs):
        session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(pipeline, "_vector_search", failing)
    monkeypatch.setattr(pipeline, "_fulltext_search", failing)

    with pytest.raises(RuntimeError, match="Both vector and fulltext"):
        pipeline.hybrid_search(db, "synthetic query")

    assert db.execute(text("SELECT 1")).scalar_one() == 1
