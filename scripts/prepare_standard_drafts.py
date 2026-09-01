"""Prepare both disease drafts; execute mode is an explicit database checkpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for item in (PROJECT_ROOT, BACKEND_ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from app.services.standard_draft_service import DraftPreparationSpec, plan_draft_preparation, prepare_standard_drafts

FATTY_SHA256 = "f0e1b1dd3b3da14e214711438060a0a7f42a3461a446db63963b35cc99d94fba"
AD_SHA256 = "96222b951522cdbb7ef211b226d95659e9dc624e684cb88240d36267d816f9df"


def configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def build_plan(args):
    specs = [
        DraftPreparationSpec("fatty_liver", args.fatty_source, FATTY_SHA256, args.fatty_version_label, args.parser_version),
        DraftPreparationSpec("ad", args.ad_source, AD_SHA256, args.ad_version_label, args.parser_version),
    ]
    return plan_draft_preparation(None, specs)


def open_transaction():
    from app.db.session import SessionLocal
    return SessionLocal()


def execute_changes(db, args):
    specs = [
        DraftPreparationSpec("fatty_liver", args.fatty_source, FATTY_SHA256, args.fatty_version_label, args.parser_version),
        DraftPreparationSpec("ad", args.ad_source, AD_SHA256, args.ad_version_label, args.parser_version),
    ]
    return prepare_standard_drafts(db, specs, admin_id=args.admin_id)


def main(argv: list[str] | None = None) -> int:
    configure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("--fatty-source", required=True, type=Path)
    parser.add_argument("--ad-source", required=True, type=Path)
    parser.add_argument("--fatty-version-label", default="fatty-liver-2026-08-25")
    parser.add_argument("--ad-version-label", default="ad-2026-08-25")
    parser.add_argument("--parser-version", default="v2")
    parser.add_argument("--admin-id", required=True, type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    db = None
    try:
        if not args.execute:
            plan = build_plan(args)
            if isinstance(plan, dict):
                payload = plan
            else:
                payload = {"status": "dry_run", "items": [item.__dict__ for item in plan.items]}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        db = open_transaction()
        result = execute_changes(db, args)
        db.commit()
        print(json.dumps({"status": "executed", "items": [item.__dict__ for item in result.items]}, ensure_ascii=False, sort_keys=True))
        return 0
    except ValueError:
        if db is not None:
            db.rollback()
        print(json.dumps({"status": "blocked", "error": "validation_failed"}, ensure_ascii=False))
        return 1
    except Exception:
        if db is not None:
            db.rollback()
        print(json.dumps({"status": "error", "error": "runtime_error"}, ensure_ascii=False))
        return 2
    finally:
        if db is not None and hasattr(db, "close"):
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
