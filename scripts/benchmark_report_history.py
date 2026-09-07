"""Reproducible scalar history benchmark, confined to an explicit local _test DB."""

import argparse, json, os, sys, time, statistics
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--page-size", type=int, choices=[20, 100], default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    from scripts.seed_operator_report_e2e import require_test_database

    url = os.environ.get("TEST_DATABASE_URL", "")
    require_test_database(url)
    if not 1 <= args.rows <= 100000:
        raise ValueError("benchmark_rows_invalid")
    from sqlalchemy import create_engine, text, event
    from sqlalchemy.orm import Session
    from app.services.report_history_query import read_history
    from app.schemas.report_history import HistoryFilters

    engine = create_engine(url)
    statements = []
    try:
        with Session(engine) as db:
            # Every synthetic row remains in this rolled-back transaction.
            owner = db.execute(
                text(
                    "INSERT INTO users(username,email,hashed_password,role) VALUES(:name,:email,'disabled','ai_operator') RETURNING id"
                ),
                {
                    "name": "benchmark-" + str(uuid4()),
                    "email": str(uuid4()) + "@test.invalid",
                },
            ).scalar_one()
            db.execute(
                text(
                    """INSERT INTO ai_reports(user_id,query,content,status,analysis_type,input_snapshot,report_document)
              SELECT :owner,'test',repeat('x',10000),'completed','longitudinal_predictive',jsonb_build_object('anonymous_case_code','CASE-ABCD-2345','disease_code','fatty_liver','visits','[]'::jsonb),jsonb_build_object('stress',repeat('x',50000)) FROM generate_series(1,:rows)"""
                ),
                {"owner": owner, "rows": args.rows},
            )
            db.execute(text("ANALYZE ai_reports"))

            def capture(conn, cursor, statement, parameters, context, many):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", capture)
            timings = []
            ids = []
            cursor = None
            try:
                while True:
                    start = time.perf_counter()
                    page = read_history(
                        db,
                        owner,
                        HistoryFilters(),
                        limit=args.page_size,
                        cursor=cursor,
                        key=b"benchmark-only-key-32-bytes-or-more",
                    )
                    timings.append((time.perf_counter() - start) * 1000)
                    ids.extend(item.id for item in page.items)
                    if not page.has_more:
                        break
                    cursor = page.next_cursor
                assert len(ids) == len(set(ids)) == args.rows
                for filters in [
                    HistoryFilters(disease_code="fatty_liver"),
                    HistoryFilters(
                        anonymous_case_code="CASE-ABCD-2345", status="completed"
                    ),
                ]:
                    assert len(
                        read_history(
                            db,
                            owner,
                            filters,
                            limit=args.page_size,
                            key=b"benchmark-only-key-32-bytes-or-more",
                        ).items
                    ) == min(args.rows, args.page_size)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            for sql in statements:
                assert all(
                    value not in sql
                    for value in (
                        "ai_reports.content",
                        "ai_reports.report_document",
                        "operator_cases",
                        "ai_reports.input_snapshot,",
                    )
                )
            explain = db.execute(
                text(
                    "EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) SELECT id,created_at FROM ai_reports WHERE user_id=:owner AND analysis_type='longitudinal_predictive' ORDER BY created_at DESC,id DESC LIMIT :limit"
                ),
                {"owner": owner, "limit": args.page_size},
            ).scalar_one()
            result = {
                "rows": args.rows,
                "page_size": args.page_size,
                "pages": len(timings),
                "p50_ms": statistics.median(timings),
                "p95_ms": sorted(timings)[max(0, int(len(timings) * 0.95) - 1)],
                "max_ms": max(timings),
                "sql_count": len(statements),
                "exact_pagination": True,
                "explain": explain,
            }
            db.rollback()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "explain"}))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
