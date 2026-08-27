"""Build a fresh, anonymous synthetic demonstration training release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for value in (ROOT, BACKEND):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from app.services.longitudinal_dataset import build_fixed_window_dataset
from app.services.longitudinal_dataset_export import export_fixed_window_dataset
from app.services.longitudinal_demonstration_data import (
    DEFAULT_SEED,
    GENERATOR_VERSION,
    build_demonstration_case_rows,
)


def _code_version() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _error(code: str) -> dict[str, object]:
    return {
        "schema_version": "longitudinal_demonstration_dataset_build.v1",
        "status": "error",
        "error": {"code": code, "message": "无法生成演示训练数据集"},
    }


def run_build(
    output_dir: Path,
    *,
    patients_per_disease: int,
    seed: int,
) -> dict[str, object]:
    rows = build_demonstration_case_rows(
        patients_per_disease=patients_per_disease,
        seed=seed,
    )
    result = build_fixed_window_dataset(rows)
    manifest = export_fixed_window_dataset(
        result,
        output_dir,
        generated_at=datetime.now(timezone.utc),
        code_version=_code_version(),
        training_profile="synthetic_demonstration",
        generator_version=GENERATOR_VERSION,
        generator_seed=seed,
    )
    return {
        "schema_version": "longitudinal_demonstration_dataset_build.v1",
        "status": "generated",
        "training_profile": "synthetic_demonstration",
        "clinical_validity_claim": False,
        "generator_version": GENERATOR_VERSION,
        "generator_seed": seed,
        "data_content_sha256": manifest["data_content_sha256"],
        "group_split_sha256": manifest["group_split_sha256"],
        "patient_count_by_disease": {
            "fatty_liver": patients_per_disease,
            "ad": patients_per_disease,
        },
    }


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成明确标注为非临床演示用途的纵向训练数据 release"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--patients-per-disease", type=int, default=30)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    try:
        payload = run_build(
            args.output_dir,
            patients_per_disease=args.patients_per_disease,
            seed=args.seed,
        )
    except FileExistsError:
        _print(_error("output_exists"))
        return 2
    except ValueError as exc:
        code = str(exc)
        _print(_error(code if code.isidentifier() else "data_invalid"))
        return 2
    except OSError:
        _print(_error("output_error"))
        return 2
    _print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
