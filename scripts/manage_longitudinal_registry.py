"""Explicit review/enable CLI for the file-based longitudinal registry."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for item in (ROOT, BACKEND):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from app.services.longitudinal_model_release import (
    ModelReleaseError,
    enable_review,
    review_candidate,
)


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _error(code: str) -> dict[str, object]:
    return {
        "status": "error",
        "error": {"code": code, "message": "无法完成纵向模型发布操作"},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    review = subparsers.add_parser("review")
    review.add_argument("--bundle-dir", type=Path)
    review.add_argument("--registry-dir", type=Path)
    review.add_argument("--reviewer")
    review.add_argument("--note")
    review.add_argument("--reviewed-at")
    enable = subparsers.add_parser("enable")
    enable.add_argument("--review-file", type=Path)
    enable.add_argument("--registry-dir", type=Path)
    enable.add_argument("--enabled-by")
    enable.add_argument("--enabled-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command not in {"review", "enable"}:
            raise ModelReleaseError("command_required")
        if args.registry_dir is None:
            raise ModelReleaseError("registry_dir_required")
        registry_root = args.registry_dir.resolve()
        if args.command == "review":
            if not all((args.bundle_dir, args.reviewer, args.note, args.reviewed_at)):
                raise ModelReleaseError("review_arguments_required")
            result = review_candidate(
                args.bundle_dir,
                registry_root,
                reviewer=args.reviewer,
                reviewed_at=_datetime(args.reviewed_at),
                note=args.note,
            )
            _print(
                {
                    "status": "reviewed",
                    "task": result.record.task,
                    "model_id": result.record.model_id,
                    "review_file": result.path.relative_to(registry_root).as_posix(),
                }
            )
        else:
            if not all((args.review_file, args.enabled_by, args.enabled_at)):
                raise ModelReleaseError("enable_arguments_required")
            result = enable_review(
                args.review_file,
                registry_root,
                enabled_by=args.enabled_by,
                enabled_at=_datetime(args.enabled_at),
            )
            _print(
                {
                    "status": "enabled",
                    "task": result.record.task,
                    "model_id": result.record.model_id,
                    "release_file": result.path.relative_to(registry_root).as_posix(),
                }
            )
        return 0
    except ModelReleaseError as error:
        _print(_error(error.code))
        return 2
    except (OSError, UnicodeError, ValueError):
        _print(_error("input_or_output_error"))
        return 2
    except Exception:
        _print(_error("runtime_error"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
