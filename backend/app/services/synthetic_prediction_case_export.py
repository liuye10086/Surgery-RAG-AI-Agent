"""Atomic, inspectable synthetic files; never imports cases into the application."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np

from app.schemas.synthetic_prediction_cases import GENERATOR_VERSION, SCHEMA_VERSION, GenerationConfig
from app.services.synthetic_prediction_cases import canonical_json, generate_cohort
from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
from app.services.synthetic_prediction_quality import assess_fixed_fixtures, assess_generation


COLLECTIONS = ("patients", "observations", "prediction_inputs", "followup_outcomes", "generation_audit")
JSONL_COLLECTIONS = (*COLLECTIONS, "fixtures", "expected_results")
DATA_FILES = tuple(f"{name}.jsonl" for name in JSONL_COLLECTIONS) + ("quality_report.json",)
SOURCE_FILES = (
    "backend/app/schemas/synthetic_prediction_cases.py",
    "backend/app/services/synthetic_prediction_cases.py",
    "backend/app/services/synthetic_prediction_fixtures.py",
    "backend/app/services/synthetic_prediction_quality.py",
    "backend/app/services/synthetic_prediction_case_export.py",
    "scripts/build_synthetic_prediction_cases.py",
    "backend/app/services/indicator_validation.py",
    "backend/app/services/operator_indicator_catalog.py",
    "backend/app/services/operator_case_validation.py",
    "backend/app/services/longitudinal_task_routing.py",
    "backend/app/schemas/longitudinal_case.py",
    "backend/app/schemas/operator_visit_context.py",
)


def content_hash(files: dict) -> str:
    return hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest()


def _source_hashes():
    root = Path(__file__).resolve().parents[3]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def _identity(config, hashes):
    full = content_hash({"generator_version": GENERATOR_VERSION, "config": config.model_dump(),
                         "source_sha256": hashes})
    return "syn-" + full[:16], full


def _code_version():
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[3],
                                capture_output=True, text=True, check=True, timeout=5)
        value = result.stdout.strip()
        return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _attach_run_id(value, run_id):
    if isinstance(value, list):
        for item in value:
            _attach_run_id(item, run_id)
    elif isinstance(value, dict):
        if value.get("source_kind") == "synthetic" and value.get("is_synthetic") is True:
            value["run_id"] = run_id
        for item in value.values():
            _attach_run_id(item, run_id)


def _quality(config, cohort, fixtures, expected):
    reports = [assess_generation(config, cohort), assess_fixed_fixtures(fixtures, expected)]
    checks = {key: value for report in reports for key, value in report["checks"].items()}
    statuses = [report["status"] for report in reports]
    status = "failed" if "failed" in statuses else "not_assessable" if "not_assessable" in statuses else "passed"
    return {"status": status, "clinical_validity_claim": False, "checks": checks}


def _file_record(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _cleanup_owned_temp(temporary, parent):
    # The caller owns exactly this mkdtemp directory, never an existing output.
    if temporary.is_symlink() or temporary.resolve().parent != parent.resolve():
        raise OSError("unsafe_temporary_path")
    if not temporary.name.startswith(".synthetic-cases-"):
        raise OSError("unsafe_temporary_name")
    shutil.rmtree(temporary)


def export_synthetic_cases(config: GenerationConfig, output_dir: Path) -> dict:
    destination = Path(output_dir).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("output_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".synthetic-cases-", dir=destination.parent))
    try:
        hashes = _source_hashes()
        run_id, full_identity = _identity(config, hashes)
        cohort = generate_cohort(config)
        fixtures, expected = build_fixed_fixtures()
        quality = _quality(config, cohort, fixtures, expected)
        data = deepcopy({**cohort, "fixtures": fixtures, "expected_results": expected})
        _attach_run_id(data, run_id)
        for name in JSONL_COLLECTIONS:
            payload = "".join(canonical_json(row) + "\n" for row in data[name])
            (temporary / f"{name}.jsonl").write_bytes(payload.encode("utf-8"))
        (temporary / "quality_report.json").write_bytes((canonical_json(quality) + "\n").encode("utf-8"))
        files = {name: _file_record(temporary / name) for name in DATA_FILES}
        manifest = {
            "schema_version": SCHEMA_VERSION, "generator_version": GENERATOR_VERSION,
            "code_version": _code_version(),
            "runtime": {"python": sys.version.split()[0], "numpy": np.__version__},
            "run_id": run_id, "run_identity_sha256": full_identity, "config": config.model_dump(),
            "source_sha256": hashes, "files": files, "data_content_sha256": content_hash(files),
            "counts": {name: len(data[name]) for name in JSONL_COLLECTIONS},
            "quality_status": quality["status"], "clinical_validity_claim": False,
            "purpose": "synthetic_software_verification_only",
            "clinical_thresholds": None, "clinical_followup_tolerance": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (temporary / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
        verification = verify_synthetic_case_export(temporary)
        if verification.get("integrity_status") != "passed":
            raise OSError("export_integrity_failed")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("output_exists")
        # Windows os.rename atomically fails if the destination already exists.
        os.rename(temporary, destination)
        return {"status": quality["status"], "run_id": run_id,
                "data_content_sha256": manifest["data_content_sha256"], "counts": manifest["counts"]}
    finally:
        if temporary.exists():
            _cleanup_owned_temp(temporary, destination.parent)


def _reject(reason):
    return {"status": "failed", "integrity_status": "failed", "reason": reason}


def verify_synthetic_case_export(output_dir: Path) -> dict:
    """Read only; recalculate links and quality, including a forged PASS report."""
    directory = Path(output_dir)
    try:
        required = {*DATA_FILES, "manifest.json"}
        if set(p.name for p in directory.iterdir()) != required:
            return _reject("file_set_mismatch")
        if any((directory / name).is_symlink() or not (directory / name).is_file() for name in required):
            return _reject("invalid_file_type")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if (manifest["schema_version"] != SCHEMA_VERSION or manifest["generator_version"] != GENERATOR_VERSION
                or manifest["clinical_validity_claim"] is not False
                or manifest["purpose"] != "synthetic_software_verification_only"
                or manifest["clinical_thresholds"] is not None
                or manifest["clinical_followup_tolerance"] is not None):
            return _reject("manifest_contract_mismatch")
        config = GenerationConfig.model_validate(manifest["config"])
        if manifest["source_sha256"] != _source_hashes():
            return _reject("source_revision_mismatch")
        run_id, full_identity = _identity(config, manifest["source_sha256"])
        if (manifest["run_id"], manifest["run_identity_sha256"]) != (run_id, full_identity):
            return _reject("run_identity_mismatch")
        files = {name: _file_record(directory / name) for name in DATA_FILES}
        if files != manifest["files"] or content_hash(files) != manifest["data_content_sha256"]:
            return _reject("file_hash_mismatch")
        data = {name: [json.loads(line) for line in (directory / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]
                for name in JSONL_COLLECTIONS}
        if {name: len(rows) for name, rows in data.items()} != manifest["counts"]:
            return _reject("count_mismatch")
        for name in ("patients", "observations", "prediction_inputs"):
            if any(row["source"].get("run_id") != run_id for row in data[name]):
                return _reject("source_run_mismatch")
        canonical_fixtures, canonical_expected = build_fixed_fixtures()
        _attach_run_id(canonical_fixtures, run_id)
        _attach_run_id(canonical_expected, run_id)
        if data["fixtures"] != canonical_fixtures or data["expected_results"] != canonical_expected:
            return _reject("fixture_reference_mismatch")
        quality = _quality(config, {key: data[key] for key in COLLECTIONS}, data["fixtures"], data["expected_results"])
        saved = json.loads((directory / "quality_report.json").read_text(encoding="utf-8"))
        if saved != quality or quality["status"] != manifest["quality_status"]:
            return _reject("quality_report_mismatch")
        return {"status": quality["status"], "integrity_status": "passed", "run_id": run_id,
                "data_content_sha256": content_hash(files), "counts": manifest["counts"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return _reject("unreadable_or_invalid_package")
