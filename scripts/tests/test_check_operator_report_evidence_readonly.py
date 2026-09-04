import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("checker", ROOT / "scripts/check_database_readonly.py")
checker = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(checker)


def test_checker_declares_evidence_storage_contract():
    assert checker.REQUIRED_COLUMNS["reference_case_windows"] >= {
        "anonymous_case_code", "dataset_release_id", "feature_summary", "eligibility_status", "timeline_sha256"
    }
    assert checker.REQUIRED_COLUMNS["ai_reports"] >= {"evidence_snapshot", "evidence_snapshot_sha256", "evidence_status"}


def test_phase_is_explicit_for_deployment_safety():
    action = next(
        item for item in checker._argument_parser()._actions
        if item.dest == "phase"
    )
    assert action.required is True


def test_postflight_runtime_and_storage_checks_fail_closed():
    assert checker._evidence_runtime_matches({"available": False}, "postflight") is False
    assert checker._evidence_storage_matches({"available": False}, "postflight") is False


def test_runtime_query_failure_is_explicit_and_not_a_pass():
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("database details must not escape")

    result = checker._collect_evidence_runtime_checks(BrokenConnection(), "postflight")

    assert result == {"available": False, "reason_code": "evidence_runtime_query_failed"}
    assert checker._evidence_runtime_matches(result, "postflight") is False


def test_postflight_source_integrity_failure_blocks_otherwise_valid_runtime():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.calls = 0

        def execute(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return Result([
                    {
                        "code": "ad", "standard_id": 1, "version_id": 4,
                        "status": "approved", "version_hash": "a" * 64,
                        "document_hash": "a" * 64, "file_path": "ad.docx",
                    },
                    {
                        "code": "fatty_liver", "standard_id": 2, "version_id": 5,
                        "status": "approved", "version_hash": "b" * 64,
                        "document_hash": "b" * 64, "file_path": "fatty.docx",
                    },
                ])
            if self.calls == 2:
                return Result([
                    {
                        "code": "ad", "logical_dataset": "ad", "dataset_release_id": "release-a",
                        "data_content_sha256": "c" * 64, "row_count": 1,
                    },
                    {
                        "code": "fatty_liver", "logical_dataset": "fatty_liver", "dataset_release_id": "release-f",
                        "data_content_sha256": "d" * 64, "row_count": 1,
                    },
                ])
            if self.calls == 3:
                return Result([
                    {"code": "ad", "total_rules": 8, "bound_rules": 7, "cross_version_sources": 0, "empty_source_texts": 0},
                    {"code": "fatty_liver", "total_rules": 11, "bound_rules": 11, "cross_version_sources": 0, "empty_source_texts": 0},
                ])
            return Result([])

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        checker,
        "_sha256_path",
        lambda path: "a" * 64 if path == "ad.docx" else "b" * 64,
    )
    try:
        result = checker._collect_evidence_runtime_checks(Connection(), "preflight")
    finally:
        monkeypatch.undo()

    assert result["standards_match"] is True
    assert result["active_releases_match"] is True
    assert result["standard_source_integrity_match"] is False
    assert checker._evidence_runtime_matches(result, "postflight") is False


def test_postflight_rejects_whitespace_only_bound_source_text(monkeypatch):
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    whitespace_source_text = "\t\n"

    class Connection:
        def __init__(self):
            self.calls = 0

        def execute(self, statement, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return Result([
                    {
                        "code": "ad", "standard_id": 1, "version_id": 4,
                        "status": "approved", "version_hash": "a" * 64,
                        "document_hash": "a" * 64, "file_path": "ad.docx",
                    },
                    {
                        "code": "fatty_liver", "standard_id": 2, "version_id": 5,
                        "status": "approved", "version_hash": "b" * 64,
                        "document_hash": "b" * 64, "file_path": "fatty.docx",
                    },
                ])
            if self.calls == 2:
                return Result([
                    {
                        "code": "ad", "logical_dataset": "ad", "dataset_release_id": "release-a",
                        "data_content_sha256": "c" * 64, "row_count": 1,
                    },
                    {
                        "code": "fatty_liver", "logical_dataset": "fatty_liver", "dataset_release_id": "release-f",
                        "data_content_sha256": "d" * 64, "row_count": 1,
                    },
                ])
            if self.calls == 3:
                query = str(statement)
                rejects_whitespace_only_text = (
                    "ss.raw_text IS NULL" in query
                    and "[:space:]" in query
                    and not any(not char.isspace() for char in whitespace_source_text)
                )
                return Result([
                    {
                        "code": "ad", "total_rules": 8, "bound_rules": 8,
                        "cross_version_sources": 0,
                        "empty_source_texts": int(rejects_whitespace_only_text),
                    },
                    {
                        "code": "fatty_liver", "total_rules": 11, "bound_rules": 11,
                        "cross_version_sources": 0, "empty_source_texts": 0,
                    },
                ])
            return Result([
                {
                    "logical_dataset": "ad", "dataset_release_id": "release-a",
                    "data_content_sha256": "c" * 64,
                    "eligibility_config_hash": checker.ELIGIBILITY_CONFIG_HASH,
                    "total_windows": 1, "eligible_windows": 1,
                },
                {
                    "logical_dataset": "fatty_liver", "dataset_release_id": "release-f",
                    "data_content_sha256": "d" * 64,
                    "eligibility_config_hash": checker.ELIGIBILITY_CONFIG_HASH,
                    "total_windows": 1, "eligible_windows": 1,
                },
            ])

    monkeypatch.setattr(
        checker,
        "_sha256_path",
        lambda path: "a" * 64 if path == "ad.docx" else "b" * 64,
    )

    result = checker._collect_evidence_runtime_checks(Connection(), "postflight")

    assert result["standards_match"] is True
    assert result["active_releases_match"] is True
    assert result["standard_source_integrity"] == [
        {"code": "ad", "total_rules": 8, "bound_rules": 8, "cross_version_sources": 0, "empty_source_texts": 1},
        {"code": "fatty_liver", "total_rules": 11, "bound_rules": 11, "cross_version_sources": 0, "empty_source_texts": 0},
    ]
    assert result["standard_source_integrity_match"] is False
    assert checker._evidence_runtime_matches(result, "postflight") is False


def test_checker_rejects_current_version_owned_by_another_standard(monkeypatch):
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.calls = 0

        def execute(self, statement, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                assert "v.standard_id AS version_standard_id" in str(statement)
                return Result([
                    {"code": "ad", "standard_id": 1, "version_id": 4,
                     "version_standard_id": 99, "status": "approved",
                     "version_hash": "a" * 64, "document_hash": "a" * 64,
                     "file_path": "ad.docx"},
                    {"code": "fatty_liver", "standard_id": 2, "version_id": 5,
                     "version_standard_id": 2, "status": "approved",
                     "version_hash": "b" * 64, "document_hash": "b" * 64,
                     "file_path": "fatty.docx"},
                ])
            if self.calls == 2:
                return Result([])
            return Result([])

    monkeypatch.setattr(
        checker, "_sha256_path", lambda path: "a" * 64 if path == "ad.docx" else "b" * 64
    )
    result = checker._collect_evidence_runtime_checks(Connection(), "preflight")

    assert result["standards"][0]["version_belongs_to_standard"] is False
    assert result["standards_match"] is False
