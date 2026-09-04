"""Build anonymized reference-case windows (dry-run unless --apply is given)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.reference_case_windows import (  # noqa: E402
    ReferenceIndexError,
    synchronize_reference_case_windows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, choices=("fatty_liver", "ad"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        with SessionLocal() as db:
            result = synchronize_reference_case_windows(db, args.dataset, apply=args.apply)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        return 0
    except ReferenceIndexError as exc:
        print(f"status=BLOCKED error_code={exc.code}")
        return 1
    except Exception:
        print("status=BLOCKED error_code=reference_build_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
