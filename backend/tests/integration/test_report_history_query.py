from datetime import datetime, timezone
from sqlalchemy import text, event
from app.schemas.report_history import HistoryFilters
from app.services.report_history_query import read_history, history_projection

KEY = b"history-test-key-" * 3


def seed(db, count=60):
    db.execute(
        text(
            """INSERT INTO ai_reports (user_id,title,query,content,status,analysis_type,input_snapshot)
        SELECT 1,'private','private','LARGE BODY','completed','predictive',
        jsonb_build_object('anonymous_case_code','CASE-ABCD-2345','disease_code','fatty_liver','disease','脂肪肝','visits',jsonb_build_array(1,2,3))
        FROM generate_series(1,:count)"""
        ),
        {"count": count},
    )
    db.commit()


def test_stable_pagination_after_deletion_and_insertion(db, integration_engine):
    seed(db)
    page = read_history(db, 1, HistoryFilters(), limit=20, key=KEY)
    assert [item.id for item in page.items] == list(range(60, 40, -1))
    with integration_engine.begin() as other:
        other.execute(text("DELETE FROM ai_reports WHERE id=60"))
        other.execute(
            text(
                "INSERT INTO ai_reports (user_id,query,status,analysis_type) VALUES(1,'new','failed','predictive')"
            )
        )
    next_page = read_history(
        db, 1, HistoryFilters(), limit=20, key=KEY, cursor=page.next_cursor
    )
    assert [item.id for item in next_page.items] == list(range(40, 20, -1))
    assert read_history(db, 2, HistoryFilters(), key=KEY).items == []
    assert page.items[0].title == "CASE-ABCD-2345纵向进展预测报告"
    assert page.items[0].visit_count == 3


def test_projection_never_fetches_large_saved_json_or_cases(db, integration_engine):
    seed(db, 1)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(integration_engine, "before_cursor_execute", capture)
    try:
        read_history(db, 1, HistoryFilters(), key=KEY)
    finally:
        event.remove(integration_engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    sql = statements[0]
    for forbidden in (
        "ai_reports.content",
        "ai_reports.report_document",
        "ai_reports.evidence_snapshot",
        "operator_cases",
    ):
        assert forbidden not in sql
    assert "ai_reports.input_snapshot," not in sql
    assert "ai_reports.prediction_result," not in sql


def test_ten_thousand_rows_have_exact_pagination_and_explain(db):
    seed(db, 10000)
    ids, cursor = [], None
    while True:
        page = read_history(db, 1, HistoryFilters(), key=KEY, limit=100, cursor=cursor)
        ids.extend(item.id for item in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
    assert ids == list(range(10000, 0, -1))
    db.execute(text("ANALYZE ai_reports"))
    plan = db.execute(
        text(
            "EXPLAIN (ANALYZE, FORMAT JSON) SELECT id,created_at FROM ai_reports WHERE user_id=1 AND analysis_type='predictive' ORDER BY created_at DESC,id DESC LIMIT 101"
        )
    ).scalar_one()
    assert plan[0]["Plan"]["Actual Rows"] == 101
    assert "ix_report_history_owner_order" in str(plan)


def test_malformed_saved_visits_do_not_break_history(db):
    seed(db, 1)
    db.execute(
        text(
            "UPDATE ai_reports SET input_snapshot=jsonb_build_object('visits','malformed')"
        )
    )
    db.commit()
    assert read_history(db, 1, HistoryFilters(), key=KEY).items[0].visit_count is None
