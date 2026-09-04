"""Safely bind current approved standard rules to manifest source segments."""

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

from app.db.session import SessionLocal
from app.services.standard_source_binding import (
    SourceBindingPlan,
    StandardSourceBindingError,
    apply_current_standard_bindings,
    plan_current_standard_bindings,
)


def configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def build_plan(db, dataset: str) -> SourceBindingPlan:
    return plan_current_standard_bindings(db, dataset)


def _plan_payload(plan: SourceBindingPlan, *, status: str, bound: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset": plan.dataset,
        "version_id": plan.version_id,
        "total_rules": plan.total_rules,
        "to_bind": len(plan.to_bind),
        "consistent": plan.consistent,
        "status": status,
    }
    if bound is not None:
        payload["bound"] = bound
    return payload


def main(argv: list[str] | None = None) -> int:
    configure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("--standard", choices=("fatty_liver", "ad"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        plan = build_plan(db, args.standard)
        if not args.apply:
            db.rollback()
            print(json.dumps(_plan_payload(plan, status="dry_run"), ensure_ascii=False, sort_keys=True))
            return 0
        bound = len(plan.to_bind)
        applied = apply_current_standard_bindings(db, plan)
        db.commit()
        print(json.dumps(_plan_payload(applied, status="applied", bound=bound), ensure_ascii=False, sort_keys=True))
        return 0
    except StandardSourceBindingError as exc:
        db.rollback()
        print(json.dumps({"status": "blocked", "error": exc.code}, ensure_ascii=False, sort_keys=True))
        return 1
    except Exception:
        db.rollback()
        print(json.dumps({"status": "error", "error": "runtime_error"}, ensure_ascii=False, sort_keys=True))
        return 2
    finally:
        if hasattr(db, "close"):
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
