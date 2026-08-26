"""Deterministic, non-overwriting local export for P0-03 datasets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from app.schemas.longitudinal_dataset import DATASET_SCHEMA_VERSION, FixedWindowSample
from app.services.longitudinal_dataset import DatasetBuildResult


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, samples: list[FixedWindowSample]) -> None:
    content = "".join(
        canonical_json(sample.model_dump(mode="json")) + "\n"
        for sample in samples
    )
    path.write_text(content, encoding="utf-8", newline="")


def _iso_utc(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def export_fixed_window_dataset(
    result: DatasetBuildResult,
    output_dir: Path,
    *,
    generated_at: datetime,
    code_version: str,
) -> dict[str, object]:
    """Atomically publish deterministic JSONL files to a fresh directory."""
    target = Path(output_dir).resolve()
    parent = target.parent
    if not parent.is_dir():
        raise FileNotFoundError(parent)
    if target.exists():
        raise FileExistsError(target)

    temporary = Path(
        tempfile.mkdtemp(dir=parent, prefix=f".{target.name}.")
    ).resolve()
    try:
        all_real_train = list(result.real_train)
        all_real_audit = list(result.real_audit)
        all_synthetic_audit = list(result.synthetic_audit)
        relative_paths: list[str] = []
        for disease in ("fatty_liver", "ad"):
            disease_dir = temporary / disease
            disease_dir.mkdir()
            cohorts = {
                "real_train.jsonl": [
                    sample
                    for sample in all_real_train
                    if sample.identity.disease == disease
                ],
                "real_audit.jsonl": [
                    sample
                    for sample in all_real_audit
                    if sample.identity.disease == disease
                ],
                "synthetic_audit.jsonl": [
                    sample
                    for sample in all_synthetic_audit
                    if sample.identity.disease == disease
                ],
            }
            for filename, samples in cohorts.items():
                path = disease_dir / filename
                _write_jsonl(path, samples)
                relative_paths.append(path.relative_to(temporary).as_posix())

        file_hashes = {
            relative_path: sha256_file(temporary / relative_path)
            for relative_path in sorted(relative_paths)
        }
        stable_content = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "minimum_visits": 3,
            "horizon_days": 365,
            "summary": result.summary.model_dump(mode="json"),
            "files": file_hashes,
        }
        data_content_sha256 = hashlib.sha256(
            canonical_json(stable_content).encode("utf-8")
        ).hexdigest()
        manifest: dict[str, object] = {
            **stable_content,
            "generated_at": _iso_utc(generated_at),
            "code_version": str(code_version or "unknown"),
            "window": "(as_of,as_of+365d]",
            "formal_training_source": "real_only",
            "synthetic_usage": "audit_only",
            "data_content_sha256": data_content_sha256,
        }
        (temporary / "manifest.json").write_text(
            canonical_json(manifest) + "\n",
            encoding="utf-8",
            newline="",
        )
        temporary.rename(target)
        return manifest
    except Exception:
        if temporary.is_dir():
            shutil.rmtree(temporary)
        raise
