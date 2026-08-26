"""Safe audit and candidate training CLI for P0-04."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.schemas.longitudinal_model_training import TASK_SPECS
from app.services.longitudinal_model_training import ModelInputError, read_dataset_manifest, read_real_train_samples, select_task_samples, train_task_to_candidate, write_candidate_bundle


def build_error_payload(code: str) -> dict[str, object]:
    return {"schema_version": "longitudinal_outcome_model_training.v1", "status": "error", "error": {"code": code, "message": "无法完成纵向结局模型操作"}}


def run_audit(dataset_dir: Path) -> dict[str, object]:
    dataset = read_dataset_manifest(dataset_dir)
    tasks = {}
    for name, task in TASK_SPECS.items():
        samples = read_real_train_samples(dataset_dir, task.disease)
        rows = select_task_samples(samples, name)
        tasks[name] = {"sample_count": len(rows), "patient_count": len({row.sample.identity.group_id for row in rows}), "positive_count": sum(row.sample.label.training_label == 1 for row in rows), "negative_count": sum(row.sample.label.training_label == 0 for row in rows)}
    return {"schema_version": "longitudinal_outcome_model_training.v1", "status": "audit_only", "dataset_manifest_sha256": dataset.manifest_sha256, "tasks": tasks}


def run_training(dataset_dir: Path, output_dir: Path, *, seed: int = 42) -> dict[str, object]:
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    dataset = read_dataset_manifest(dataset_dir)
    results = {}
    fit_dir = output / ".fit"
    try:
        for name, task in TASK_SPECS.items():
            rows = select_task_samples(read_real_train_samples(dataset_dir, task.disease), name)
            result = train_task_to_candidate(rows, task, dataset, fit_dir, seed=seed)
            bundle = write_candidate_bundle(result, output)
            results[name] = {
                "bundle": bundle.bundle_dir.name,
                "model": bundle.model_path.name,
                "metadata": bundle.metadata_path.name,
                "model_id": bundle.metadata.model_contract.model_id,
                "model_version": bundle.metadata.model_contract.model_version,
                "artifact_sha256": bundle.metadata.model_contract.artifact_sha256,
                "status": "candidate",
                "production_enabled": False,
            }
    finally:
        if fit_dir.is_dir():
            shutil.rmtree(fit_dir)
    return {"schema_version": "longitudinal_outcome_model_training.v1", "status": "candidate", "tasks": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--export-artifact", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.export_artifact:
            raise ModelInputError("production_artifact_export_not_authorized")
        if args.dataset_dir is None:
            raise ModelInputError("dataset_dir_required")
        if args.train:
            if args.output_dir is None:
                raise ModelInputError("output_dir_required")
            payload = run_training(args.dataset_dir, args.output_dir, seed=args.seed)
        else:
            payload = run_audit(args.dataset_dir)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except FileExistsError:
        print(json.dumps(build_error_payload("output_exists"), ensure_ascii=False, sort_keys=True))
        return 2
    except ModelInputError as error:
        code = str(error) if str(error) in {"dataset_dir_required", "output_dir_required", "production_artifact_export_not_authorized"} else "input_or_output_error"
        print(json.dumps(build_error_payload(code), ensure_ascii=False, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps(build_error_payload("input_or_output_error"), ensure_ascii=False, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps(build_error_payload("runtime_error"), ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
