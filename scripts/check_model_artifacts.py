"""Print and optionally verify model artifact SHA-256 checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for item in (ROOT, BACKEND):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_manifest(directory: Path, patterns: tuple[str, ...] = ("*.joblib", "*.meta.json")) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for pattern in patterns:
        for path in directory.rglob(pattern):
            if path.is_file():
                digest = sha256_file(path)
                manifest[str(path.relative_to(directory)).replace("\\", "/")] = digest
    return dict(sorted(manifest.items()))


def check_bundle(bundle_dir: Path) -> dict[str, object]:
    from app.services.longitudinal_model_registry import validate_candidate_bundle

    result = validate_candidate_bundle(Path(bundle_dir), inspect_model=True)
    return {
        "status": result.status.status,
        "reason_code": result.status.reason_code,
        "task": result.status.task,
        "lifecycle_status": result.status.lifecycle_status,
        "model_id": result.status.model_id,
        "model_version": result.status.model_version,
        "artifact_sha256": result.status.artifact_sha256,
        "prediction_executed": result.prediction_executed,
    }


def check_registry(registry_dir: Path) -> dict[str, object]:
    from app.services.longitudinal_model_registry import load_model_registry

    datasets: dict[str, object] = {}
    for dataset in ("fatty_liver", "ad"):
        registry = load_model_registry(dataset, registry_root=registry_dir)
        datasets[dataset] = {
            "outcomes": {
                task: entry.status.model_dump(mode="json")
                for task, entry in registry.outcomes.items()
            },
            "stage": registry.stage.model_dump(mode="json"),
            "trend": registry.trend.model_dump(mode="json"),
        }
    return {
        "schema_version": "longitudinal_model_registry.v1",
        "datasets": datasets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--models-dir", type=Path)
    modes.add_argument("--bundle-dir", type=Path)
    modes.add_argument("--registry-dir", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    if args.bundle_dir is not None:
        payload = check_bundle(args.bundle_dir)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["reason_code"] == "lifecycle_not_enabled" else 1
    if args.registry_dir is not None:
        print(
            json.dumps(
                check_registry(args.registry_dir),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    current = sha256_manifest(args.models_dir)
    print(json.dumps(current, ensure_ascii=False, indent=2))
    if args.baseline:
        expected = json.loads(args.baseline.read_text(encoding="utf-8"))
        return 0 if current == expected else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
