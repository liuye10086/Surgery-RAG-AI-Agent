"""Import one approved manifest and optionally publish it atomically."""

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

from app.services.standard_manifest import load_standard_manifest
from app.services.standard_manifest_import import import_manifest_rules, plan_manifest_import
from app.services.standard_lifecycle import publish_review_version, submit_review_version


def configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def build_plan(args):
    manifest = load_standard_manifest(args.manifest)
    return plan_manifest_import(None, manifest=manifest, version_id=args.version_id)


def open_transaction():
    from app.db.session import SessionLocal
    return SessionLocal()


def execute_changes(db, args):
    manifest = load_standard_manifest(args.manifest)
    result = import_manifest_rules(db, manifest=manifest, version_id=args.version_id, admin_id=args.admin_id) if args.import_rules else None
    published = None
    if args.publish:
        submit_review_version(db, version_id=args.version_id, commit=False)
        published = publish_review_version(db, version_id=args.version_id, admin_id=args.admin_id, commit=False)
    return result, published


def main(argv: list[str] | None = None) -> int:
    configure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--version-id", required=True, type=int)
    parser.add_argument("--admin-id", required=True, type=int)
    parser.add_argument("--import-rules", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    db = None
    try:
        if not args.execute:
            plan = build_plan(args)
            payload = plan if isinstance(plan, dict) else {"status": "dry_run", "rule_entry_ids": plan.rule_entry_ids, "skipped_entry_ids": plan.skipped_entry_ids}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        db = open_transaction()
        result, published = execute_changes(db, args)
        db.commit()
        print(json.dumps({"status": "executed", "created_rule_entry_ids": getattr(result, "created_rule_entry_ids", []), "published": published is not None}, ensure_ascii=False, sort_keys=True))
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
