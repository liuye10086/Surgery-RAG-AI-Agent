"""Audit or train complete fatty-liver/AD candidate model suites."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.schemas.longitudinal_model_training import TASK_SPECS
from app.services.disease_progression import get_progression_adapter
from app.services.longitudinal_dataset import PatientTimeline, TimelineVisit
from app.services.longitudinal_group_split import (
    GroupSplitError,
    read_disease_group_splits,
)
from app.services.longitudinal_model_training import (
    ModelInputError,
    read_dataset_manifest,
    read_training_samples,
    select_task_samples,
    train_outcome_task,
    write_outcome_candidate_bundle,
)
from app.services.longitudinal_stage_training import (
    StageTrainingError,
    build_stage_rows,
    train_stage_candidate,
    write_stage_candidate_bundle,
)
from app.services.longitudinal_trend_training import (
    TREND_CONTRACTS,
    TrendTrainingError,
    build_trend_rows,
    train_trend_candidate,
    write_trend_candidate_bundle,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _error(code: str) -> dict[str, object]:
    return {
        "schema_version": "longitudinal_model_suite_training.v1",
        "status": "error",
        "error": {
            "code": code,
            "message": "无法完成纵向完整模型组操作",
        },
    }


def _date_map(value: object) -> dict[str, date]:
    if not isinstance(value, dict):
        raise ModelInputError("timeline_invalid")
    try:
        return {
            str(key): date.fromisoformat(str(item))
            for key, item in value.items()
            if item not in (None, "")
        }
    except ValueError as exc:
        raise ModelInputError("timeline_invalid") from exc


def training_file_for(dataset, disease: str) -> str:
    return dataset.training_file_by_disease.get(
        disease, f"{disease}/real_train.jsonl"
    )


def timeline_file_for(dataset, disease: str) -> str:
    return dataset.timeline_file_by_disease.get(
        disease, f"{disease}/real_timelines.jsonl"
    )


def read_training_timelines(
    dataset_dir: Path,
    disease: str,
) -> list[PatientTimeline]:
    dataset = read_dataset_manifest(dataset_dir)
    relative = timeline_file_for(dataset, disease)
    if relative not in dataset.file_sha256_by_path:
        raise ModelInputError("timeline_file_missing_from_manifest")
    path = Path(dataset_dir) / relative
    if not path.is_file() or _sha256(path) != dataset.file_sha256(relative):
        raise ModelInputError("timeline_hash_mismatch")
    adapter = get_progression_adapter(disease)
    timelines: list[PatientTimeline] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            group_id = str(raw["group_id"])
            if (
                raw.get("schema_version") != "longitudinal_training_timeline.v1"
                or raw.get("disease") != disease
                or not group_id.startswith("patient.v1.")
                or group_id in seen
                or not isinstance(raw.get("visits"), list)
            ):
                raise ModelInputError("timeline_invalid")
            expected_provenance = (
                "synthetic_demonstration"
                if dataset.training_profile == "synthetic_demonstration"
                else "real_only"
            )
            if raw.get("provenance", "real_only") != expected_provenance:
                raise ModelInputError("timeline_provenance_mismatch")
            visits = tuple(
                TimelineVisit(
                    visit_date=date.fromisoformat(str(visit["visit_date"])),
                    indicators=tuple(
                        dict(indicator)
                        for indicator in visit.get("indicators", [])
                        if isinstance(indicator, dict)
                    ),
                    patient_age=visit.get("patient_age"),
                    sex=visit.get("sex"),
                    input_position=index,
                )
                for index, visit in enumerate(raw["visits"])
            )
        except ModelInputError:
            raise
        except Exception as exc:
            raise ModelInputError("timeline_invalid") from exc
        if len(visits) < 3 or tuple(sorted(visits, key=lambda item: item.visit_date)) != visits:
            raise ModelInputError("timeline_invalid")
        seen.add(group_id)
        timelines.append(
            PatientTimeline(
                adapter=adapter,
                source_dataset="anonymous_training_release",
                patient_label=group_id,
                group_id=group_id,
                is_synthetic=(dataset.training_profile == "synthetic_demonstration"),
                source_document=None,
                import_version=None,
                final_stage=raw.get("final_stage"),
                event_dates=_date_map(raw.get("event_dates", {})),
                visits=visits,
            )
        )
    if not timelines:
        raise ModelInputError("timeline_file_empty")
    return timelines


def _bundle_record(bundle, dataset_dir: Path, output_dir: Path, *, artifact_type: str, indicator: str | None = None) -> dict[str, object]:
    return {
        "task": bundle.metadata.task,
        "artifact_type": artifact_type,
        "indicator": indicator,
        "model_path": bundle.model_path.relative_to(output_dir).as_posix(),
        "metadata_path": bundle.metadata_path.relative_to(output_dir).as_posix(),
        "evaluation_path": bundle.evaluation_path.relative_to(output_dir).as_posix(),
        "manifest_path": Path(
            os.path.relpath(
                Path(dataset_dir).joinpath("manifest.json").resolve(),
                Path(output_dir).resolve(),
            )
        ).as_posix(),
        "model_sha256": _sha256(bundle.model_path),
        "metadata_sha256": _sha256(bundle.metadata_path),
        "evaluation_sha256": _sha256(bundle.evaluation_path),
    }


def timelines_for_split(
    timelines: list[PatientTimeline], split
) -> list[PatientTimeline]:
    allowed = set(split.assignments())
    return [timeline for timeline in timelines if timeline.group_id in allowed]


def train_disease_suite(
    *,
    disease: str,
    dataset_dir: Path,
    dataset_input,
    split,
    timelines: list[PatientTimeline],
    output_dir: Path,
    seed: int,
) -> dict[str, object]:
    timelines = timelines_for_split(timelines, split)
    bundles: list[dict[str, object]] = []
    models: dict[str, dict[str, object]] = {}
    fit_dir = output_dir / ".fit"
    training_file = training_file_for(dataset_input, disease)
    training_samples = read_training_samples(
        dataset_dir, disease, dataset=dataset_input
    )
    allow_synthetic = dataset_input.training_profile == "synthetic_demonstration"
    for task_name, task in TASK_SPECS.items():
        if task.disease != disease:
            continue
        selected_task = task.model_copy(update={"dataset_file": training_file})
        rows = select_task_samples(
            training_samples, task_name
        )
        candidate = train_outcome_task(
            rows, selected_task, split, dataset_input, fit_dir, seed=seed
        )
        bundle = write_outcome_candidate_bundle(candidate, output_dir / "bundles")
        bundles.append(
            _bundle_record(
                bundle, dataset_dir, output_dir, artifact_type="outcome"
            )
        )
        models[task_name] = {"status": "candidate"}

    try:
        stage_rows = build_stage_rows(
            timelines,
            disease,
            split,
            allow_synthetic=allow_synthetic,
        )
        stage_candidate = train_stage_candidate(
            stage_rows, split, dataset_input, fit_dir, seed=seed
        )
        stage_bundle = write_stage_candidate_bundle(
            stage_candidate, output_dir / "bundles"
        )
        bundles.append(
            _bundle_record(
                stage_bundle, dataset_dir, output_dir, artifact_type="stage"
            )
        )
        models[stage_candidate.task] = {"status": "candidate"}
    except StageTrainingError as exc:
        models[f"{disease}.next_stage"] = {
            "status": "not_estimable",
            "reason_code": str(exc),
        }

    for (contract_disease, indicator), contract in sorted(TREND_CONTRACTS.items()):
        if contract_disease != disease:
            continue
        task = f"{disease}.next_visit_trend.{indicator}"
        try:
            trend_rows = build_trend_rows(
                timelines,
                contract,
                split,
                allow_synthetic=allow_synthetic,
            )
            trend_candidate = train_trend_candidate(
                trend_rows, contract, split, dataset_input, fit_dir, seed=seed
            )
            trend_bundle = write_trend_candidate_bundle(
                trend_candidate, output_dir / "bundles"
            )
            bundles.append(
                _bundle_record(
                    trend_bundle,
                    dataset_dir,
                    output_dir,
                    artifact_type="trend",
                    indicator=indicator,
                )
            )
            models[task] = {"status": "candidate"}
        except TrendTrainingError as exc:
            models[task] = {
                "status": "not_estimable",
                "reason_code": str(exc),
            }
    if fit_dir.is_dir():
        shutil.rmtree(fit_dir)
    return {
        "status": (
            "candidate"
            if all(item["status"] == "candidate" for item in models.values())
            else "incomplete"
        ),
        "bundles": bundles,
        "models": models,
    }


def run_audit(dataset_dir: Path, disease: str) -> dict[str, object]:
    dataset = read_dataset_manifest(dataset_dir)
    splits = read_disease_group_splits(dataset_dir)
    diseases = ("fatty_liver", "ad") if disease == "all" else (disease,)
    return {
        "schema_version": "longitudinal_model_suite_training.v1",
        "status": "audit_only",
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "diseases": {
            item: {
                "split_sha256": splits[item].sha256,
                "timeline_count": len(read_training_timelines(dataset_dir, item)),
            }
            for item in diseases
        },
    }


def run_training(
    dataset_dir: Path,
    output_dir: Path,
    *,
    disease: str,
    seed: int,
) -> dict[str, object]:
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    dataset = read_dataset_manifest(dataset_dir)
    splits = read_disease_group_splits(dataset_dir)
    diseases = ("fatty_liver", "ad") if disease == "all" else (disease,)
    summaries: dict[str, object] = {}
    for item in diseases:
        disease_dir = output / item
        disease_dir.mkdir()
        trained = train_disease_suite(
            disease=item,
            dataset_dir=Path(dataset_dir),
            dataset_input=dataset,
            split=splits[item],
            timelines=read_training_timelines(dataset_dir, item),
            output_dir=disease_dir,
            seed=seed,
        )
        manifest_relative = Path(
            os.path.relpath(
                Path(dataset_dir).joinpath("manifest.json").resolve(),
                disease_dir.resolve(),
            )
        ).as_posix()
        for bundle in trained["bundles"]:
            bundle.setdefault("manifest_path", manifest_relative)
        release_set_id = f"{item}-{dataset.data_content_sha256[:12]}-{splits[item].sha256[:12]}"
        candidate = {
            "schema_version": "longitudinal_disease_release_set_candidate.v1",
            "dataset": item,
            "release_set_id": release_set_id,
            "data_release_id": dataset.run_id or f"dataset-{dataset.data_content_sha256[:12]}",
            "dataset_manifest": "dataset/manifest.json",
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "split_sha256": splits[item].sha256,
            "production_enabled": False,
            "bundles": trained["bundles"],
            "models": trained["models"],
            "status": trained["status"],
        }
        manifest_path = disease_dir / f"{release_set_id}.candidate-set.json"
        manifest_path.write_text(
            json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        summaries[item] = {
            "status": trained["status"],
            "release_set_id": release_set_id,
            "candidate_manifest": manifest_path.name,
            "model_count": len(trained["models"]),
            "candidate_count": len(trained["bundles"]),
        }
    return {
        "schema_version": "longitudinal_model_suite_training.v1",
        "status": (
            "candidate"
            if all(item["status"] == "candidate" for item in summaries.values())
            else "incomplete"
        ),
        "diseases": summaries,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--disease", choices=["fatty_liver", "ad", "all"], default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dataset_dir is None:
            raise ModelInputError("dataset_dir_required")
        if args.train:
            if args.output_dir is None:
                raise ModelInputError("output_dir_required")
            payload = run_training(
                args.dataset_dir,
                args.output_dir,
                disease=args.disease,
                seed=args.seed,
            )
        else:
            payload = run_audit(args.dataset_dir, args.disease)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except FileExistsError:
        print(json.dumps(_error("output_exists"), ensure_ascii=False, sort_keys=True))
        return 2
    except (ModelInputError, GroupSplitError, StageTrainingError, TrendTrainingError, KeyError):
        print(json.dumps(_error("input_or_output_error"), ensure_ascii=False, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps(_error("input_or_output_error"), ensure_ascii=False, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps(_error("runtime_error"), ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
