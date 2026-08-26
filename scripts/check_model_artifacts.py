"""Print and optionally verify model artifact SHA-256 checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtifactValidation:
    valid: bool
    missing_fields: list[str] = field(default_factory=list)
    prediction_executed: bool = False


def validate_candidate_metadata(model_path: Path, meta_path: Path, dataset_dir: Path | None = None) -> ArtifactValidation:
    """Validate P0-04 metadata without executing model prediction."""
    required = ["schema_version", "task", "dataset_manifest_sha256", "data_content_sha256", "dataset_file_sha256", "feature_order_sha256", "status"]
    if not model_path.is_file() or not meta_path.is_file():
        return ArtifactValidation(False, ["model_or_metadata_missing"])
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        joblib = __import__("joblib")
        joblib.load(model_path)
    except Exception:
        return ArtifactValidation(False, ["artifact_unloadable"])
    missing = [key for key in required if not metadata.get(key)]
    if metadata.get("schema_version") != "longitudinal_outcome_model_training.v1":
        missing.append("schema_version")
    if metadata.get("status") not in {"candidate", "reviewed", "enabled"}:
        missing.append("status")
    return ArtifactValidation(not missing, sorted(set(missing)))


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    current = sha256_manifest(args.models_dir)
    print(json.dumps(current, ensure_ascii=False, indent=2))
    if args.baseline:
        expected = json.loads(args.baseline.read_text(encoding="utf-8"))
        return 0 if current == expected else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
