"""Deterministic local export contracts for the P0-03 dataset."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services.longitudinal_dataset import build_fixed_window_dataset
from app.services.longitudinal_dataset_export import (
    export_fixed_window_dataset,
    sha256_file,
)


def patient_rows(
    patient_label: str,
    *,
    source_dataset: str = "longitudinal_300",
    disease_name: str = "脂肪肝",
    event_dates: dict | None = None,
    final_stage="fatty_liver",
    is_synthetic: bool = False,
    indicator_name: str = "ALT",
) -> list[dict]:
    dates = ("2023-01-01", "2023-06-01", "2024-01-01")
    return [
        {
            "record_id": index,
            "disease_name": disease_name,
            "patient_label": patient_label,
            "indicators": [{"name": indicator_name, "value": 10 + index}],
            "metadata": {
                "visit_date": visit_date,
                "patient_age": 60,
                "sex": "female",
                "final_stage": final_stage,
                "event_dates": event_dates or {},
                "source_dataset": source_dataset,
                "is_synthetic": is_synthetic,
                "import_version": "1.0.0",
            },
        }
        for index, visit_date in enumerate(dates, start=1)
    ]


def mixed_result():
    rows = []
    rows += patient_rows(
        "fatty-real",
        event_dates={"cirrhosis_date": "2024-06-01"},
        final_stage="cirrhosis",
    )
    rows += patient_rows(
        "fatty-synthetic",
        event_dates={"cirrhosis_date": "2024-06-01"},
        final_stage="cirrhosis",
        is_synthetic=True,
    )
    rows += patient_rows(
        "ad-real",
        source_dataset="ad_longitudinal_300",
        disease_name="阿尔茨海默病",
        indicator_name="MMSE",
        event_dates={"dementia_date": "2024-06-01"},
        final_stage="1",
    )
    rows += patient_rows(
        "ad-synthetic",
        source_dataset="ad_longitudinal_300",
        disease_name="阿尔茨海默病",
        indicator_name="MMSE",
        event_dates={"dementia_date": "2024-06-01"},
        final_stage="1",
        is_synthetic=True,
    )
    return build_fixed_window_dataset(rows)


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_export_writes_expected_files_per_disease(tmp_path):
    target = tmp_path / "dataset"

    manifest = export_fixed_window_dataset(
        mixed_result(),
        target,
        generated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        code_version="test-revision",
    )

    for disease in ("fatty_liver", "ad"):
        disease_dir = target / disease
        assert {path.name for path in disease_dir.iterdir()} == {
            "real_train.jsonl",
            "real_audit.jsonl",
            "synthetic_audit.jsonl",
        }
        assert all(
            row["identity"]["is_synthetic"] is False
            and row["label"]["status"] in {"positive", "negative"}
            for row in _jsonl(disease_dir / "real_train.jsonl")
        )
        assert all(
            row["identity"]["is_synthetic"] is True
            for row in _jsonl(disease_dir / "synthetic_audit.jsonl")
        )

    assert (target / "manifest.json").is_file()
    assert manifest["schema_version"] == "longitudinal_fixed_window_dataset.v1"
    assert manifest["minimum_visits"] == 3
    assert manifest["horizon_days"] == 365
    assert manifest["window"] == "(as_of,as_of+365d]"


def test_export_is_deterministic_across_run_timestamps(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    result = mixed_result()

    manifest_one = export_fixed_window_dataset(
        result,
        first,
        generated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        code_version="same-revision",
    )
    manifest_two = export_fixed_window_dataset(
        result,
        second,
        generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        code_version="same-revision",
    )

    assert manifest_one["generated_at"] != manifest_two["generated_at"]
    assert manifest_one["data_content_sha256"] == manifest_two["data_content_sha256"]
    assert manifest_one["files"] == manifest_two["files"]
    for relative_path in manifest_one["files"]:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()
        assert sha256_file(first / relative_path) == sha256_file(second / relative_path)


def test_export_rows_follow_stable_sample_order(tmp_path):
    target = tmp_path / "dataset"
    export_fixed_window_dataset(
        mixed_result(),
        target,
        generated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        code_version="test-revision",
    )

    for disease in ("fatty_liver", "ad"):
        rows = _jsonl(target / disease / "real_audit.jsonl")
        keys = [
            (
                row["identity"]["disease"],
                row["identity"]["source_dataset"],
                row["identity"]["patient_label"],
                row["identity"]["as_of"],
            )
            for row in rows
        ]
        assert keys == sorted(keys)


def test_existing_target_is_never_overwritten(tmp_path):
    target = tmp_path / "dataset"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_fixed_window_dataset(
            mixed_result(),
            target,
            generated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            code_version="test-revision",
        )

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(target.iterdir()) == [sentinel]


def test_write_failure_leaves_no_final_target(monkeypatch, tmp_path):
    target = tmp_path / "dataset"

    def fail_write(*args, **kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(Path, "write_text", fail_write)

    with pytest.raises(OSError):
        export_fixed_window_dataset(
            mixed_result(),
            target,
            generated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            code_version="test-revision",
        )

    assert not target.exists()
    assert not list(tmp_path.glob(".dataset.*"))
