"""Build an anonymous P0-03 audit summary or an explicit local export."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for import_path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from app.core.config import settings
from app.schemas.longitudinal_dataset import DATASET_SCHEMA_VERSION
from app.services.longitudinal_dataset import (
    DatasetValidationError,
    build_fixed_window_dataset,
    load_case_rows,
)
from app.services.longitudinal_dataset_export import export_fixed_window_dataset


def configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def build_error_payload(
    code: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "status": "error",
        "error": {
            "code": code,
            "message": "无法构建固定窗口纵向数据集",
            "details": details or {},
        },
    }


def _safe_validation_details(error: DatasetValidationError) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in error.details.items():
        if key.endswith("_count") and isinstance(value, int) and value >= 0:
            safe[key] = value
    return safe


def get_code_version() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def run_build(
    *,
    database_url: str,
    output_dir: Path | None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    timestamp = generated_at or datetime.now(timezone.utc)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                result = build_fixed_window_dataset(load_case_rows(connection))
                manifest = None
                if output_dir is not None:
                    manifest = export_fixed_window_dataset(
                        result,
                        output_dir,
                        generated_at=timestamp,
                        code_version=get_code_version(),
                    )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()

    payload: dict[str, object] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "generated_at": timestamp.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "mode": "exported" if output_dir is not None else "audit_only",
        "summary": result.summary.model_dump(mode="json"),
    }
    if output_dir is not None and manifest is not None:
        payload["output_dir"] = str(output_dir.resolve())
        payload["data_content_sha256"] = manifest["data_content_sha256"]
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读检查固定窗口数据集；指定目录时导出本地审计文件",
    )
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    configure_stdout_utf8()
    args = _parse_args(argv)
    try:
        payload = run_build(
            database_url=settings.DATABASE_URL,
            output_dir=args.output_dir,
        )
    except SQLAlchemyError:
        _print_json(build_error_payload("database_unavailable"))
        return 2
    except DatasetValidationError as error:
        _print_json(
            build_error_payload(error.code, _safe_validation_details(error))
        )
        return 2
    except FileExistsError:
        _print_json(build_error_payload("output_exists"))
        return 2
    except OSError:
        _print_json(build_error_payload("output_error"))
        return 2
    except Exception:
        _print_json(build_error_payload("runtime_error"))
        return 2
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
