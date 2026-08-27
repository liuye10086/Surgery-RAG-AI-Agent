"""Explicit review, enable, and rollback commands for disease release sets."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.longitudinal_release_set import (
    ReleaseSetError,
    deactivate_release_set,
    enable_release_set,
    review_release_set,
    rollback_release_set,
)


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command")

    review = commands.add_parser("review")
    review.add_argument("--candidate-manifest", type=Path)
    review.add_argument("--registry-dir", type=Path)
    review.add_argument("--reviewer")
    review.add_argument("--note")
    review.add_argument("--reviewed-at")

    enable = commands.add_parser("enable")
    enable.add_argument("--review-file", type=Path)
    enable.add_argument("--registry-dir", type=Path)
    enable.add_argument("--enabled-by")
    enable.add_argument("--enabled-at")

    rollback = commands.add_parser("rollback")
    rollback.add_argument("--dataset", choices=["fatty_liver", "ad"])
    rollback.add_argument("--target-release-set")
    rollback.add_argument("--registry-dir", type=Path)
    rollback.add_argument("--actor")
    rollback.add_argument("--changed-at")

    deactivate = commands.add_parser("deactivate")
    deactivate.add_argument("--dataset", choices=["fatty_liver", "ad"])
    deactivate.add_argument("--expected-release-set")
    deactivate.add_argument("--registry-dir", type=Path)
    deactivate.add_argument("--actor")
    deactivate.add_argument("--changed-at")
    return parser


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _error(code: str) -> dict[str, object]:
    return {
        "schema_version": "longitudinal_disease_release_set_operation.v1",
        "status": "error",
        "error": {"code": code, "message": "无法完成模型组发布操作"},
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "review":
            if not all(
                (
                    args.candidate_manifest,
                    args.registry_dir,
                    args.reviewer,
                    args.note,
                    args.reviewed_at,
                )
            ):
                raise ReleaseSetError("arguments_required")
            result = review_release_set(
                args.candidate_manifest,
                args.registry_dir,
                reviewer=args.reviewer,
                reviewed_at=_time(args.reviewed_at),
                note=args.note,
            )
            _print(
                {
                    "schema_version": "longitudinal_disease_release_set_operation.v1",
                    "status": "reviewed",
                    "dataset": result.release_set.dataset,
                    "release_set_id": result.release_set.release_set_id,
                    "release_set_sha256": result.release_set.record_sha256,
                    "review_file": result.review_path.relative_to(
                        args.registry_dir.resolve()
                    ).as_posix(),
                }
            )
            return 0
        if args.command == "enable":
            if not all(
                (
                    args.review_file,
                    args.registry_dir,
                    args.enabled_by,
                    args.enabled_at,
                )
            ):
                raise ReleaseSetError("arguments_required")
            pointer = enable_release_set(
                args.review_file,
                args.registry_dir,
                enabled_by=args.enabled_by,
                enabled_at=_time(args.enabled_at),
            )
            _print(
                {
                    "schema_version": "longitudinal_disease_release_set_operation.v1",
                    "status": "enabled",
                    "dataset": pointer.dataset,
                    "release_set_id": pointer.release_set_id,
                    "release_set_sha256": pointer.release_set_sha256,
                    "changed_at": pointer.changed_at.isoformat(),
                }
            )
            return 0
        if args.command == "rollback":
            if not all(
                (
                    args.dataset,
                    args.target_release_set,
                    args.registry_dir,
                    args.actor,
                    args.changed_at,
                )
            ):
                raise ReleaseSetError("arguments_required")
            pointer = rollback_release_set(
                args.dataset,
                args.target_release_set,
                args.registry_dir,
                actor=args.actor,
                changed_at=_time(args.changed_at),
            )
            _print(
                {
                    "schema_version": "longitudinal_disease_release_set_operation.v1",
                    "status": "rolled_back",
                    "dataset": pointer.dataset,
                    "release_set_id": pointer.release_set_id,
                    "release_set_sha256": pointer.release_set_sha256,
                    "changed_at": pointer.changed_at.isoformat(),
                }
            )
            return 0
        if args.command == "deactivate":
            if not all(
                (
                    args.dataset,
                    args.expected_release_set,
                    args.registry_dir,
                    args.actor,
                    args.changed_at,
                )
            ):
                raise ReleaseSetError("arguments_required")
            result = deactivate_release_set(
                args.dataset,
                args.expected_release_set,
                args.registry_dir,
                actor=args.actor,
                changed_at=_time(args.changed_at),
            )
            _print(
                {
                    "schema_version": "longitudinal_disease_release_set_operation.v1",
                    "status": "deactivated",
                    "dataset": result.dataset,
                    "previous_release_set_id": result.previous_release_set_id,
                    "changed_at": result.changed_at.isoformat(),
                }
            )
            return 0
        raise ReleaseSetError("arguments_required")
    except ReleaseSetError as exc:
        _print(_error(str(exc)))
        return 2
    except (OSError, ValueError):
        _print(_error("input_or_output_error"))
        return 2
    except Exception:
        _print(_error("runtime_error"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
