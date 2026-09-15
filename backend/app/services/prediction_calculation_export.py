"""Verified synthetic baseline calculations written to a fresh artifact directory."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

from app.services.synthetic_prediction_cases import canonical_json
from app.services.synthetic_prediction_case_export import content_hash, verify_synthetic_case_export
from app.services.prediction_calculation import (
    build_engineering_samples, evaluate_baselines, predict_baselines, project_calculation_inputs,
)


VERSION = "synthetic_prediction_calculation.v1"
JSONL_FILES = ("features", "samples", "predictions", "paired_rows")
JSON_FILES = ("evaluation", "bootstrap_plans")
DATA_FILES = tuple(f"{key}.jsonl" for key in JSONL_FILES) + tuple(f"{key}.json" for key in JSON_FILES) + ("summary.md",)
SOURCE_FILES = (
    "backend/app/services/prediction_calculation.py",
    "backend/app/services/prediction_calculation_metrics.py",
    "backend/app/services/prediction_calculation_export.py",
    "scripts/evaluate_synthetic_prediction_cases.py",
)
CALCULATION_CONFIG = {"bootstrap_seed": 20260910, "bootstrap_iterations": 2000, "confidence_level": 0.95,
                      "rng": "numpy.Generator(PCG64)", "quantile_method": "linear",
                      "rng_mapping": "reset_same_seed_per_task_pool_branch_sorted_groups",
                      "time_adapter": "synthetic_calendar_days.v1", "label_policy": "synthetic_nominal_date.v1"}


def _record(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _code_hashes():
    root = Path(__file__).resolve().parents[3]
    return {name: _record((root / name).read_bytes())["sha256"] for name in SOURCE_FILES}


def _source_snapshot(directory):
    verification = verify_synthetic_case_export(directory)
    if verification.get("status") != "passed" or verification.get("integrity_status") != "passed":
        raise ValueError("source_not_verified")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if (manifest["data_content_sha256"] != verification["data_content_sha256"]
            or content_hash(manifest["files"]) != verification["data_content_sha256"]
            or manifest["run_id"] != verification["run_id"]):
        raise ValueError("source_changed")
    data = {}
    for name in ("patients", "prediction_inputs", "followup_outcomes", "generation_audit"):
        path = directory / f"{name}.jsonl"
        if path.is_symlink():
            raise ValueError("source_changed")
        raw = path.read_bytes()
        if _record(raw) != manifest["files"][path.name]:
            raise ValueError("source_changed")
        data[name] = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    return data, verification


def _calculate(data):
    features = project_calculation_inputs(data["prediction_inputs"])
    predictions = predict_baselines(features)
    samples = build_engineering_samples(data["patients"], data["prediction_inputs"], data["followup_outcomes"], data["generation_audit"])
    calculated = evaluate_baselines(samples, predictions)
    return {"features": features, "samples": samples, "predictions": predictions, **calculated}


def _number(value):
    return "不可估计" if value is None else f"{value:.4f}"


def _summary(data):
    lines = ["# 合成四任务离线计算结果", "",
             "本文件仅记录合成工程演练。没有训练候选模型，所有临床性能结论为不可判定；这不是正式阶段二冻结或阶段三临床评价。", "",
             "## 挑战池的基线描述", "",
             "MAE／RMSE／偏差使用各任务原单位；历史外推与保持当前值的增益仅在相同历史子集配对。", "",
             "| 任务 | 分支 | 合格锚点／有效目标／配对 | MAE | RMSE | 偏差 | 配对MAE增益 | MAE 95%工程CI |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in data["evaluation"]["comparisons"]:
        if c["pool"] != "challenge_pool":
            continue
        n, s = c["counts"], c["statistics"]
        interval = c["intervals"]["mae"]
        ci = f'{_number(interval["lower"])} ～ {_number(interval["upper"])}'
        lines.append(f'| {c["task_id"]} | {c["branch"]} | {n["N_branch_eligible"]}/{n["N_label_valid"]}/{n["N_pair_valid"]} | '
                     f'{_number(s["mae"])} | {_number(s["rmse"])} | {_number(s["bias"])} | {_number(s["mae_gain"])} | {ci} |')
    lines += ["", "完整资格、目标缺失／待定、输出失败与四种配对状态在evaluation.json；所有样本和预测记录均保留。",
              "开发池只有描述性统计。挑战池按依赖组作2,000次同组同重数配对重采样，95%工程区间不证明真实覆盖或临床样本支持。",
              "", "## 下一步", "", "在本计算框架上开展候选模型及D03流程增量成对比较，训练内标准化；之后最小应用接入和隔离全链路验收。",
              "真实路线仍需A3正式组样、A4样本量／分区／门槛、A5审核冻结，再做真实离线比较及获准接入发布。", ""]
    return "\n".join(lines)


def _payloads(data):
    files = {f"{name}.jsonl": "".join(canonical_json(row) + "\n" for row in data[name]).encode("utf-8") for name in JSONL_FILES}
    files.update({f"{name}.json": (canonical_json(data[name]) + "\n").encode("utf-8") for name in JSON_FILES})
    files["summary.md"] = _summary(data).encode("utf-8")
    return files


def _identity(source, hashes):
    digest = content_hash({"schema_version": VERSION, "source_data_content_sha256": source["data_content_sha256"],
                           "code_sha256": hashes, "config": CALCULATION_CONFIG})
    return "calc-" + digest[:16], digest


def _remove_owned(directory, parent):
    if directory.is_symlink() or directory.resolve().parent != parent.resolve() or not directory.name.startswith(".prediction-calculation-"):
        raise OSError("unsafe_cleanup_path")
    shutil.rmtree(directory)


def evaluate_synthetic_package(source_dir: Path, output_dir: Path) -> dict:
    source_dir, destination = Path(source_dir).resolve(), Path(output_dir).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("output_exists")
    if destination.resolve().is_relative_to(source_dir):
        raise ValueError("output_inside_source")
    source_data, source = _source_snapshot(source_dir)
    calculated = _calculate(source_data)
    payloads = _payloads(calculated)
    hashes = _code_hashes()
    run_id, identity_hash = _identity(source, hashes)
    records = {name: _record(raw) for name, raw in payloads.items()}
    counts = {name: len(calculated[name]) for name in JSONL_FILES}
    counts.update(comparisons=len(calculated["evaluation"]["comparisons"]), bootstrap_plans=len(calculated["bootstrap_plans"]))
    manifest = {"schema_version": VERSION, "run_id": run_id, "run_identity_sha256": identity_hash,
                "source_run_id": source["run_id"], "source_data_content_sha256": source["data_content_sha256"],
                "source_relative_path": os.path.relpath(source_dir, destination),
                "code_sha256": hashes, "config": CALCULATION_CONFIG,
                "runtime": {"python": sys.version.split()[0], "numpy": np.__version__},
                "files": records, "data_content_sha256": content_hash(records), "counts": counts,
                "clinical_validity_claim": False, "clinical_status": "not_assessable",
                "engineering_status": "passed", "created_at": datetime.now(timezone.utc).isoformat()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".prediction-calculation-", dir=destination.parent))
    try:
        for name, raw in payloads.items():
            (temporary / name).write_bytes(raw)
        (temporary / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
        # For sibling directories, the relative source reference resolves identically.
        verification = verify_calculation_export(temporary)
        if verification["status"] != "passed":
            raise ValueError("calculation_not_verified")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("output_exists")
        os.rename(temporary, destination)
        return {"status": "passed", "clinical_status": "not_assessable", "run_id": run_id,
                "data_content_sha256": manifest["data_content_sha256"], "counts": counts}
    finally:
        if temporary.exists():
            _remove_owned(temporary, destination.parent)


def verify_calculation_export(output_dir: Path) -> dict:
    directory = Path(output_dir)
    def reject(reason):
        return {"status": "failed", "reason": reason}
    try:
        expected_names = {*DATA_FILES, "manifest.json"}
        if set(p.name for p in directory.iterdir()) != expected_names:
            return reject("file_set_mismatch")
        if any((directory / name).is_symlink() or not (directory / name).is_file() for name in expected_names):
            return reject("invalid_file_type")
        manifest = json.loads((directory / "manifest.json").read_bytes())
        if (manifest["schema_version"] != VERSION or manifest["clinical_validity_claim"] is not False
                or manifest["clinical_status"] != "not_assessable" or manifest["engineering_status"] != "passed"
                or manifest["config"] != CALCULATION_CONFIG or manifest["code_sha256"] != _code_hashes()):
            return reject("manifest_mismatch")
        payloads = {name: (directory / name).read_bytes() for name in DATA_FILES}
        records = {name: _record(raw) for name, raw in payloads.items()}
        if records != manifest["files"] or content_hash(records) != manifest["data_content_sha256"]:
            return reject("file_hash_mismatch")
        data, source = _source_snapshot((directory / manifest["source_relative_path"]).resolve())
        run_id, identity_hash = _identity(source, _code_hashes())
        if (manifest["source_run_id"] != source["run_id"] or manifest["source_data_content_sha256"] != source["data_content_sha256"]
                or manifest["run_id"] != run_id or manifest["run_identity_sha256"] != identity_hash):
            return reject("source_identity_mismatch")
        calculated = _calculate(data)
        if payloads != _payloads(calculated):
            return reject("calculation_mismatch")
        counts = {name: len(calculated[name]) for name in JSONL_FILES}
        counts.update(comparisons=len(calculated["evaluation"]["comparisons"]), bootstrap_plans=len(calculated["bootstrap_plans"]))
        if counts != manifest["counts"]:
            return reject("count_mismatch")
        return {"status": "passed", "clinical_status": "not_assessable", "run_id": run_id,
                "data_content_sha256": content_hash(records), "counts": counts}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return reject("unreadable_or_invalid_calculation")
