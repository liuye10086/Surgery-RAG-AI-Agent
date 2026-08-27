"""Deterministic, non-overwriting local export for P0-03 datasets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Literal

from app.schemas.longitudinal_dataset import DATASET_SCHEMA_VERSION, FixedWindowSample
from app.services.longitudinal_dataset import DatasetBuildResult
from app.services.longitudinal_group_split import (
    make_disease_group_split,
    write_group_splits,
)


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


def _write_timeline_jsonl(
    path: Path,
    timelines,
    *,
    provenance: Literal["real_only", "synthetic_demonstration"],
) -> None:
    rows = []
    for patient in sorted(timelines, key=lambda item: item.group_id):
        rows.append(
            {
                "schema_version": "longitudinal_training_timeline.v1",
                "disease": patient.adapter.dataset,
                "group_id": patient.group_id,
                "provenance": provenance,
                "final_stage": patient.final_stage,
                "event_dates": {
                    key: value.isoformat()
                    for key, value in sorted(patient.event_dates.items())
                    if value is not None
                },
                "visits": [
                    {
                        "visit_date": visit.visit_date.isoformat(),
                        "patient_age": visit.patient_age,
                        "sex": visit.sex,
                        "indicators": [dict(indicator) for indicator in visit.indicators],
                    }
                    for visit in patient.visits
                ],
            }
        )
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="",
    )


def _iso_utc(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _anonymous_source_provenance(
    samples: list[FixedWindowSample],
) -> list[dict[str, str]]:
    source_hashes: set[str] = set()
    for sample in samples:
        identity = sample.identity
        source_hashes.add(
            hashlib.sha256(
                canonical_json(
                    {
                        "source_dataset": identity.source_dataset,
                        "source_document": identity.source_document,
                        "import_version": identity.import_version,
                    }
                ).encode("utf-8")
            ).hexdigest()
        )
    return [
        {"source_id": f"source-{value[:12]}", "sha256": value}
        for value in sorted(source_hashes)
    ]


def export_fixed_window_dataset(
    result: DatasetBuildResult,
    output_dir: Path,
    *,
    generated_at: datetime,
    code_version: str,
    split_seed: int = 42,
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
    training_profile: Literal["real_only", "synthetic_demonstration"] = "real_only",
    generator_version: str | None = None,
    generator_seed: int | None = None,
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
        all_real_timelines = list(result.real_timelines)
        all_synthetic_timelines = list(result.synthetic_timelines)
        if training_profile == "synthetic_demonstration":
            if not generator_version or generator_seed is None:
                raise ValueError("demonstration_generator_contract_required")
            all_training = all_real_train + [
                sample
                for sample in all_synthetic_audit
                if sample.label.status in {"positive", "negative"}
            ]
            all_training_timelines = all_real_timelines + all_synthetic_timelines
            training_filename = "demonstration_train.jsonl"
            timeline_filename = "demonstration_timelines.jsonl"
            timeline_provenance = "synthetic_demonstration"
        else:
            all_training = all_real_train
            all_training_timelines = all_real_timelines
            training_filename = "real_train.jsonl"
            timeline_filename = "real_timelines.jsonl"
            timeline_provenance = "real_only"
        relative_paths: list[str] = []
        for disease in ("fatty_liver", "ad"):
            disease_dir = temporary / disease
            disease_dir.mkdir()
            cohorts = {
                training_filename: [
                    sample
                    for sample in all_training
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
            timeline_path = disease_dir / timeline_filename
            _write_timeline_jsonl(
                timeline_path,
                [
                    patient
                    for patient in all_training_timelines
                    if patient.adapter.dataset == disease
                ],
                provenance=timeline_provenance,
            )
            relative_paths.append(
                timeline_path.relative_to(temporary).as_posix()
            )

        splits = [
            make_disease_group_split(
                all_training,
                disease,
                seed=split_seed,
                validation_fraction=validation_fraction,
                test_fraction=test_fraction,
            )
            for disease in ("fatty_liver", "ad")
        ]
        group_split_path = write_group_splits(temporary, splits)
        group_split_relative = group_split_path.relative_to(temporary).as_posix()
        relative_paths.append(group_split_relative)

        file_hashes = {
            relative_path: sha256_file(temporary / relative_path)
            for relative_path in sorted(relative_paths)
        }
        generator_contract = (
            {"version": generator_version, "seed": generator_seed}
            if training_profile == "synthetic_demonstration"
            else None
        )
        stable_content = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "minimum_visits": 3,
            "horizon_days": 365,
            "training_profile": training_profile,
            "clinical_validity_claim": False,
            "generator": generator_contract,
            "summary": result.summary.model_dump(mode="json"),
            "files": file_hashes,
        }
        data_content_sha256 = hashlib.sha256(
            canonical_json(stable_content).encode("utf-8")
        ).hexdigest()
        manifest: dict[str, object] = {
            **stable_content,
            "run_id": f"dataset-{data_content_sha256[:12]}",
            "generated_at": _iso_utc(generated_at),
            "code_version": str(code_version or "unknown"),
            "source_provenance": _anonymous_source_provenance(
                all_real_train + all_real_audit + all_synthetic_audit
            ),
            "group_split_file": group_split_relative,
            "group_split_sha256": file_hashes[group_split_relative],
            "window": "(as_of,as_of+365d]",
            "training_profile": training_profile,
            "formal_training_source": training_profile,
            "synthetic_usage": (
                "training_and_evaluation_for_demonstration_only"
                if training_profile == "synthetic_demonstration"
                else "audit_only"
            ),
            "clinical_validity_claim": False,
            "training_file_by_disease": {
                disease: f"{disease}/{training_filename}"
                for disease in ("fatty_liver", "ad")
            },
            "timeline_file_by_disease": {
                disease: f"{disease}/{timeline_filename}"
                for disease in ("fatty_liver", "ad")
            },
            "generator": generator_contract,
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
