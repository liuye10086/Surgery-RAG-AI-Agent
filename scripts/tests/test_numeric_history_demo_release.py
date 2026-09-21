import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "outputs/numeric-history-acceptance/2026-09-20-v2/result.json"
SOURCE_SHA = "3b333b090186e6c09fe938106bf2a176328e1d591b1bf6d56cf5ecbd7cd38296"
SOURCE_DATA_SHA = "2a18dee7fe1dcb89b583c5c7091f44b45607f7d4c2e9a93112dae26303bab426"
LEGACY_SHA = "32b8069f92dab3e104f3668c3639cdc6e5461f5bedf61a4f7590ce2cef478215"
HISTORY_SHA = "a6816ed1a30d9a65ae089f67746e98473f0514732883d98a2843d3bc90db2464"
RENDERER_SHA = "38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558"
ACCEPTANCE_SHA = "3dd8473c6df25aeb84c7e5c2782caef6e420e60227578062108a9edf30332c37"


def identities():
    return {
        "source": {
            "source_run_id": "syn-0aa14c3fe543c3b5",
            "source_manifest_sha256": SOURCE_SHA,
            "data_content_sha256": SOURCE_DATA_SHA,
        },
        "legacy": {"bundle_sha256": LEGACY_SHA},
        "history": {"bundle_sha256": HISTORY_SHA},
        "renderer": {"manifest_sha256": RENDERER_SHA},
    }


def runtime():
    return {
        "python_version": "3.11.4",
        "node_version": "22.15.0",
        "playwright_version": "1.55.0",
        "fonttools_version": "4.59.1",
        "chromium_version": "140.0.7339.16",
    }


def test_real_frozen_acceptance_is_bound_to_all_release_identities():
    from scripts.numeric_history_demo_release import validate_acceptance_result

    result = validate_acceptance_result(ACCEPTANCE, identities())
    assert result == {
        "acceptance_result_sha256": ACCEPTANCE_SHA,
        "status": "passed",
        "planned_reports": 5,
        "worker_invocations": 5,
        "completed_reports": 5,
        "audited_invocations": 5,
        "page_errors": [],
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("status",), "failed"),
        (("is_synthetic",), False),
        (("clinical_validity_claim",), True),
        (("identities", "source", "source_manifest_sha256"), "0" * 64),
        (("identities", "source", "data_content_sha256"), "0" * 64),
        (("identities", "legacy", "bundle_sha256"), "0" * 64),
        (("identities", "history", "bundle_sha256"), "0" * 64),
        (("identities", "renderer", "manifest_sha256"), "0" * 64),
        (("external_llm", "planned_reports"), 4),
        (("external_llm", "worker_invocations"), 4),
        (("external_llm", "completed_reports"), 4),
        (("external_llm", "audited_invocations"), 4),
        (("checks", "page_errors"), ["Error"]),
    ],
)
def test_acceptance_tampering_fails_closed(tmp_path, path, value):
    from scripts.numeric_history_demo_release import validate_acceptance_result

    raw = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    changed = tmp_path / "result.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="^frozen_acceptance_mismatch$"):
        validate_acceptance_result(changed, identities())


def test_acceptance_rejects_missing_oversized_and_symlink_files(tmp_path, monkeypatch):
    from scripts import numeric_history_demo_release as release

    with pytest.raises(ValueError, match="^frozen_acceptance_mismatch$"):
        release.validate_acceptance_result(tmp_path / "missing.json", identities())
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="^frozen_acceptance_mismatch$"):
        release.validate_acceptance_result(oversized, identities())
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(ACCEPTANCE)
    except OSError:
        original = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: True if self == ACCEPTANCE else original(self),
        )
        link = ACCEPTANCE
    with pytest.raises(ValueError, match="^frozen_acceptance_mismatch$"):
        release.validate_acceptance_result(link, identities())


def test_acceptance_rejects_current_identity_drift():
    from scripts.numeric_history_demo_release import validate_acceptance_result

    current = identities()
    current["history"]["bundle_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="^frozen_acceptance_mismatch$"):
        validate_acceptance_result(ACCEPTANCE, current)


def test_git_gate_uses_argument_arrays_and_returns_head(monkeypatch):
    from scripts import numeric_history_demo_release as release

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        output = "2" * 40 + "\n" if command[1:3] == ["rev-parse", "HEAD"] else ""
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(release.subprocess, "run", run)
    assert release.validate_git_release_state(ROOT, apply=False) == "2" * 40
    assert calls == [
        (
            ["git", "rev-parse", "HEAD"],
            {
                "cwd": ROOT,
                "check": True,
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "shell": False,
            },
        ),
        (
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            {
                "cwd": ROOT,
                "check": True,
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "shell": False,
            },
        ),
    ]


@pytest.mark.parametrize("apply", [False, True])
def test_git_gate_allows_only_explicit_document_changes(monkeypatch, apply):
    from scripts import numeric_history_demo_release as release

    status = "\n".join(
        [
            " M docs/superpowers/plans/2026-09-16-prediction-model-refactor-phase-4-history-integration.md",
            " M docs/superpowers/specs/2026-09-09-prediction-model-refactor-master-design.md",
            "?? docs/superpowers/specs/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-design.md",
            "?? docs/superpowers/plans/2026-09-20-prediction-model-refactor-phase-5-local-demo-release.md",
        ]
    )
    replies = iter(["2" * 40 + "\n", status + "\n"])
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=next(replies)),
    )
    assert release.validate_git_release_state(ROOT, apply=apply) == "2" * 40


@pytest.mark.parametrize(
    "status",
    [
        " M backend/app/main.py\n",
        "?? scripts/hidden.py\n",
        " M frontend/src/App.vue\n",
        " M backend/tests/test_secret.py\n",
        "R  docs/safe.md -> scripts/unsafe.py\n",
    ],
)
def test_git_gate_rejects_uncommitted_code(monkeypatch, status):
    from scripts import numeric_history_demo_release as release

    replies = iter(["2" * 40 + "\n", status])
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=next(replies)),
    )
    with pytest.raises(ValueError, match="^uncommitted_release_code$"):
        release.validate_git_release_state(ROOT, apply=True)


@pytest.mark.parametrize("head", ["", "main", "2" * 39, "G" * 40])
def test_git_gate_rejects_missing_or_invalid_head(monkeypatch, head):
    from scripts import numeric_history_demo_release as release

    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=head + "\n"),
    )
    with pytest.raises(ValueError, match="^git_identity_required$"):
        release.validate_git_release_state(ROOT, apply=False)


def test_release_record_builder_and_allowed_transitions():
    from scripts.numeric_history_demo_release import build_release_record, transition_release

    started = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    stopped = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    acceptance = {
        "acceptance_result_sha256": ACCEPTANCE_SHA,
    }
    record = build_release_record(
        "2026-09-20-v1",
        {**identities(), "acceptance": acceptance},
        "2" * 40,
        runtime(),
        started,
    )
    assert record.status == "starting"
    assert record.metrics.jobs.completed == 0
    running = transition_release(record, "running", at=started)
    assert running.status == "running" and running.stopped_at is None
    done = transition_release(running, "stopped", at=stopped)
    assert done.status == "stopped" and done.stopped_at == stopped
    assert transition_release(record, "failed", at=stopped).status == "failed"
    assert transition_release(running, "failed", at=stopped).status == "failed"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("starting", "stopped"),
        ("running", "starting"),
        ("stopped", "running"),
        ("failed", "running"),
    ],
)
def test_release_record_rejects_invalid_transitions(current, target):
    from scripts.numeric_history_demo_release import build_release_record, transition_release

    now = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    record = build_release_record(
        "2026-09-20-v1",
        {**identities(), "acceptance": {"acceptance_result_sha256": ACCEPTANCE_SHA}},
        "2" * 40,
        runtime(),
        now,
    )
    if current == "running":
        record = transition_release(record, "running", at=now)
    elif current == "stopped":
        record = transition_release(transition_release(record, "running", at=now), "stopped", at=now)
    elif current == "failed":
        record = transition_release(record, "failed", at=now)
    with pytest.raises(ValueError, match="^invalid_release_transition$"):
        transition_release(record, target, at=now)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _ScalarsResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _MappingsResult:
    def __init__(self, values):
        self.values = values

    def mappings(self):
        return self

    def all(self):
        return self.values


def test_database_inspection_is_read_only_and_uses_database_facts():
    from scripts.numeric_history_demo_release import inspect_demo_database

    replies = iter(
        [
            _ScalarResult(None),
            _ScalarResult("surgery_rag_phase4_test"),
            _ScalarResult("0031"),
            _ScalarResult(0),
            _ScalarResult(0),
            _ScalarResult(0),
        ]
    )
    statements = []

    class Connection:
        def execute(self, statement, parameters=None):
            statements.append((str(statement), parameters))
            return next(replies)

    result = inspect_demo_database(Connection())
    assert result == {
        "database": "surgery_rag_phase4_test",
        "alembic_version": "0031",
        "counts": {"users": 0, "operator_cases": 0, "ai_reports": 0},
    }
    assert [statement for statement, _ in statements] == [
        "SET TRANSACTION READ ONLY",
        "SELECT current_database()",
        "SELECT version_num FROM alembic_version",
        "SELECT count(*) FROM users",
        "SELECT count(*) FROM operator_cases",
        "SELECT count(*) FROM ai_reports",
    ]
    assert all(parameters is None for _, parameters in statements)


@pytest.mark.parametrize(
    ("replies", "error"),
    [
        (
            [None, "business", "0031", 0, 0, 0],
            "isolated_test_database_required",
        ),
        (
            [None, "surgery_rag_phase4_test", "0030", 0, 0, 0],
            "phase4_migration_required",
        ),
        (
            [None, "surgery_rag_phase4_test", "0031", 0, 1, 0],
            "clean_test_database_required",
        ),
    ],
)
def test_database_inspection_fails_closed(replies, error):
    from scripts.numeric_history_demo_release import inspect_demo_database

    values = iter(_ScalarResult(value) for value in replies)

    class Connection:
        def execute(self, statement, parameters=None):
            return next(values)

    with pytest.raises(ValueError, match=f"^{error}$"):
        inspect_demo_database(Connection())


def test_seed_demo_database_reuses_frozen_conversion_in_one_outer_transaction(
    tmp_path, monkeypatch
):
    from scripts import numeric_history_demo_release as release

    calls = []
    session_factory = object()

    class Connection:
        def in_transaction(self):
            return True

        def execute(self, statement, parameters=None):
            sql = str(statement)
            calls.append((sql, parameters))
            if sql.startswith("INSERT INTO users"):
                return _ScalarsResult([11, 12, 13])
            if sql.startswith("SELECT id, anonymous_case_code"):
                return _MappingsResult(
                    [
                        {
                            "id": 21,
                            "anonymous_case_code": "CASE-AAA",
                            "subject_id": "syn-a",
                        },
                        {
                            "id": 22,
                            "anonymous_case_code": "CASE-BBB",
                            "subject_id": "syn-b",
                        },
                    ]
                )
            return _ScalarResult(None)

    connection = Connection()

    def fake_sessionmaker(**kwargs):
        assert kwargs == {
            "bind": connection,
            "expire_on_commit": False,
            "join_transaction_mode": "rollback_only",
        }
        return session_factory

    def fake_convert(source_dir, source_identity, output):
        assert source_dir == tmp_path / "source"
        assert source_identity is not frozen["source"]
        assert source_identity == frozen["source"]
        calls.append(("convert", output.parent.name))
        return output

    def fake_seed(factory, package, user_id):
        assert factory is session_factory
        assert package.name == "source-package"
        assert user_id == 11
        calls.append(("seed", user_id))
        return [21, 22]

    frozen = identities()
    frozen["source"]["subjects"] = ["syn-a", "syn-b"]
    original = json.loads(json.dumps(frozen))
    monkeypatch.setattr(release, "sessionmaker", fake_sessionmaker, raising=False)
    monkeypatch.setattr(release, "convert_source_package", fake_convert, raising=False)
    monkeypatch.setattr(release, "seed_prediction_cases", fake_seed, raising=False)

    seeded = release.seed_demo_database(
        connection,
        tmp_path / "source",
        frozen,
    )

    assert frozen == original
    assert seeded == {
        "user_ids": {
            "primary_operator": 11,
            "secondary_operator": 12,
            "doctor": 13,
        },
        "case_ids": [21, 22],
        "subjects": [
            {
                "case_id": 21,
                "anonymous_case_code": "CASE-AAA",
                "subject_id": "syn-a",
            },
            {
                "case_id": 22,
                "anonymous_case_code": "CASE-BBB",
                "subject_id": "syn-b",
            },
        ],
    }
    serialized = json.dumps(seeded)
    assert "token" not in serialized and "password" not in serialized
    assert any(sql.startswith("INSERT INTO diseases") for sql, _ in calls if isinstance(sql, str))


def test_seed_demo_database_requires_callers_outer_transaction(tmp_path):
    from scripts.numeric_history_demo_release import seed_demo_database

    connection = SimpleNamespace(in_transaction=lambda: False)
    with pytest.raises(ValueError, match="^demo_seed_transaction_required$"):
        seed_demo_database(connection, tmp_path, identities())


def test_atomic_release_write_validates_fsyncs_and_replaces(tmp_path, monkeypatch):
    from scripts import numeric_history_demo_release as release

    now = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    record = release.build_release_record(
        "2026-09-20-v1",
        {**identities(), "acceptance": {"acceptance_result_sha256": ACCEPTANCE_SHA}},
        "2" * 40,
        runtime(),
        now,
    )
    target = tmp_path / "release.json"
    calls = []
    original_fsync = release.os.fsync
    original_replace = release.os.replace

    def fsync(fd):
        calls.append("fsync")
        return original_fsync(fd)

    def replace(source, destination):
        calls.append((Path(source).parent, Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(release.os, "fsync", fsync)
    monkeypatch.setattr(release.os, "replace", replace)
    release.atomic_write_release(target, record)
    assert calls[0] == "fsync"
    assert calls[1] == (tmp_path, target)
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "starting"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_release_write_removes_temporary_file_on_failure(tmp_path, monkeypatch):
    from scripts import numeric_history_demo_release as release

    now = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    record = release.build_release_record(
        "2026-09-20-v1",
        {**identities(), "acceptance": {"acceptance_result_sha256": ACCEPTANCE_SHA}},
        "2" * 40,
        runtime(),
        now,
    )
    monkeypatch.setattr(release.os, "replace", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        release.atomic_write_release(tmp_path / "release.json", record)
    assert list(tmp_path.iterdir()) == []


def _session_checks():
    return {
        "schema_version": "numeric_demo_session_checks.v1",
        "performed": ["non_owner_404", "wrong_role_403", "idempotency_replay"],
        "admission": {
            "submissions": 2,
            "accepted": 1,
            "idempotency_replays": 1,
            "admission_disabled": 0,
            "permission_denied": 0,
            "invalid_input": 0,
            "conflict": 0,
            "non_owner_404": 1,
            "wrong_role_403": 1,
            "disease_permission_denied": 0,
        },
    }


def _fact(report_id, *, status="completed", seconds=0, error_code=None):
    started = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    return {
        "report_id": report_id,
        "status": status,
        "error_code": error_code,
        "last_execution_phase": "terminal",
        "failure_phase": None,
        "finished_at": started + timedelta(seconds=seconds),
    }


def _phase_event(report_id, seq, phase, seconds):
    started = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    return {
        "report_id": report_id,
        "event_seq": seq,
        "event_kind": "phase_entered",
        "phase": phase,
        "task": None,
        "batch_id": "8b0f4f6e-0000-4000-8000-000000000001",
        "created_at": started + timedelta(seconds=seconds),
    }


def _facts(**overrides):
    started = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    batch = "8b0f4f6e-0000-4000-8000-000000000001"
    facts = {
        "external_records": 0,
        "reports": [
            {"report_id": 8, "status": "completed", "published": True,
             "context_ok": True, "snapshot_ok": True, "evidence_ok": True,
             "document_ok": True},
            {"report_id": 9, "status": "completed", "published": True,
             "context_ok": True, "snapshot_ok": True, "evidence_ok": True,
             "document_ok": True},
        ],
        "jobs": [_fact(8, seconds=90), _fact(9, status="cancelled", seconds=5)],
        "audit": [
            _phase_event(8, 1, "model_loading", 0),
            _phase_event(8, 2, "prediction", 10),
            _phase_event(8, 3, "standard_evidence", 40),
            _phase_event(8, 4, "rendering", 55),
            _phase_event(8, 5, "persistence", 70),
            {"report_id": 8, "event_seq": 6, "event_kind": "invocation_started",
             "phase": "standard_evidence", "task": "report_narrative",
             "batch_id": batch, "created_at": started + timedelta(seconds=50)},
            {"report_id": 8, "event_seq": 7, "event_kind": "task_finished",
             "phase": "standard_evidence", "task": "report_narrative",
             "batch_id": batch, "created_at": started + timedelta(seconds=65)},
        ],
        "pdf": [
            {"report_id": 8, "state": "ready", "verified": True},
            {"report_id": 9, "state": "failed", "verified": False},
        ],
        "downloads": 4,
        "session": _session_checks()["admission"],
        "identity": {
            "source_matches": True,
            "legacy_bundle_matches": True,
            "history_bundle_matches": True,
            "renderer_matches": True,
            "acceptance_matches": True,
            "git_commit_matches": True,
        },
    }
    facts.update(overrides)
    return facts


def test_release_metrics_count_every_job_state_and_unsettled_work():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["jobs"] = [
        _fact(8, seconds=90),
        _fact(9, status="cancelled", seconds=5),
        _fact(10, status="queued"),
        _fact(11, status="running"),
        _fact(12, status="failed", error_code="phase_timeout"),
    ]
    facts["jobs"][2]["finished_at"] = None
    facts["jobs"][3]["finished_at"] = None
    metrics = build_release_metrics(facts)
    assert metrics.jobs.model_dump() == {
        "queued": 1,
        "running": 1,
        "completed": 1,
        "failed": 1,
        "cancelled": 1,
        "unsettled": 2,
        "phase_timeouts": 1,
        "phase_timeout_phases": ["unknown"],
    }


def test_release_metrics_attribute_phase_durations_from_audit_order():
    from scripts.numeric_history_demo_release import build_release_metrics

    timings = build_release_metrics(_facts()).timings
    assert timings.model_loading.model_dump() == {
        "samples": 1, "total_ms": 10000, "max_ms": 10000}
    assert timings.prediction.model_dump() == {
        "samples": 1, "total_ms": 30000, "max_ms": 30000}
    assert timings.standard_evidence.model_dump() == {
        "samples": 1, "total_ms": 15000, "max_ms": 15000}
    assert timings.rendering.model_dump() == {
        "samples": 1, "total_ms": 15000, "max_ms": 15000}
    # The last phase ends at the job's own finish time, not at a later event.
    assert timings.persistence.model_dump() == {
        "samples": 1, "total_ms": 20000, "max_ms": 20000}


def test_release_metrics_leave_phase_unsampled_when_the_job_never_finished():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["jobs"] = [_fact(8)]
    facts["jobs"][0]["finished_at"] = None
    timings = build_release_metrics(facts).timings
    assert timings.persistence.model_dump() == {
        "samples": 0, "total_ms": 0, "max_ms": 0}
    assert timings.model_loading.samples == 1


def test_release_metrics_close_each_llm_invocation_against_its_batch_order():
    from scripts.numeric_history_demo_release import build_release_metrics

    assert build_release_metrics(_facts()).llm_audit.model_dump() == {
        "invocation_started": 1,
        "task_finished": 1,
        "closed_reports": 1,
        "unclosed_reports": 0,
    }


def test_release_metrics_report_an_invocation_without_a_finish_as_unclosed():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["audit"] = [
        event for event in facts["audit"] if event["event_kind"] != "task_finished"
    ]
    assert build_release_metrics(facts).llm_audit.model_dump() == {
        "invocation_started": 1,
        "task_finished": 0,
        "closed_reports": 0,
        "unclosed_reports": 1,
    }


@pytest.mark.parametrize("mutation", ["reversed", "foreign_batch"])
def test_release_metrics_fail_closed_on_incoherent_audit_order(mutation):
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    events = facts["audit"]
    if mutation == "reversed":
        events[5]["created_at"], events[6]["created_at"] = (
            events[6]["created_at"],
            events[5]["created_at"],
        )
    else:
        events[6] = {**events[6], "batch_id": "8b0f4f6e-0000-4000-8000-0000000000ff"}
    with pytest.raises(ValueError, match="^demo_audit_integrity_failed$"):
        build_release_metrics(facts)


def test_release_metrics_separate_completed_jobs_from_unreadable_saved_facts():
    """A completed job is never derived from per-prediction availability."""
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["reports"][1]["document_ok"] = False
    metrics = build_release_metrics(facts)
    assert metrics.jobs.completed == 1
    assert metrics.jobs.cancelled == 1
    assert metrics.history.model_dump() == {"verified_reports": 1, "mismatches": 1}


@pytest.mark.parametrize(
    "flag", ["context_ok", "snapshot_ok", "evidence_ok", "document_ok"]
)
def test_release_metrics_count_any_unverified_saved_identity_as_a_mismatch(flag):
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["reports"][0][flag] = False
    assert build_release_metrics(facts).history.model_dump() == {
        "verified_reports": 1, "mismatches": 1}


def test_release_metrics_count_archive_states_downloads_and_byte_verification():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["pdf"] = [
        {"report_id": 8, "state": "ready", "verified": True},
        {"report_id": 9, "state": "missing", "verified": False},
        {"report_id": 10, "state": "corrupt", "verified": False},
        {"report_id": 11, "state": "failed", "verified": False},
        {"report_id": 12, "state": "ready", "verified": False},
    ]
    assert build_release_metrics(facts).pdf.model_dump() == {
        "ready": 2,
        "failed": 1,
        "missing": 1,
        "corrupt": 1,
        "downloads": 4,
        "bytes_verified": 1,
        "sha_mismatches": 1,
    }


def test_release_metrics_use_only_outcomes_the_session_recorded():
    from scripts.numeric_history_demo_release import build_release_metrics

    metrics = build_release_metrics(_facts())
    assert metrics.admission.model_dump() == {
        "requests": 2,
        "idempotency_replays": 1,
        "rejected": 0,
        "admission_disabled": 0,
        "permission_denied": 0,
        "invalid_input": 0,
        "conflict": 0,
    }
    assert metrics.authorization.model_dump() == {
        "non_owner_404": 1,
        "wrong_role_403": 1,
        "disease_permission_denied": 0,
    }


def test_release_metrics_without_a_session_record_report_zero_not_a_pass():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["session"] = None
    metrics = build_release_metrics(facts)
    assert metrics.admission.requests == 0
    assert metrics.admission.idempotency_replays == 0
    assert metrics.authorization.non_owner_404 == 0
    assert metrics.authorization.wrong_role_403 == 0


def test_release_metrics_fail_closed_when_records_outside_the_seeded_scope_exist():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["external_records"] = 1
    with pytest.raises(ValueError, match="^demo_external_records_present$"):
        build_release_metrics(facts)


def test_release_metrics_are_engineering_only_and_never_claim_clinical_value():
    from scripts.numeric_history_demo_release import build_release_metrics

    metrics = build_release_metrics(_facts())
    encoded = metrics.model_dump_json()
    assert set(metrics.model_dump()) == {
        "admission", "jobs", "timings", "llm_audit", "authorization",
        "history", "pdf", "identity",
    }
    for forbidden in ("mae", "calibration", "accuracy", "benefit", "subgroup"):
        assert forbidden not in encoded


def test_release_metrics_report_identity_matches_as_explicit_booleans():
    from scripts.numeric_history_demo_release import build_release_metrics

    assert build_release_metrics(_facts()).identity.model_dump() == {
        "source_matches": True,
        "legacy_bundle_matches": True,
        "history_bundle_matches": True,
        "renderer_matches": True,
        "acceptance_matches": True,
        "git_commit_matches": True,
    }


def test_safe_diagnostic_keeps_only_type_stage_and_basename_location():
    from scripts.numeric_history_demo_release import safe_diagnostic

    def boom():
        raise RuntimeError("postgresql://secret:password@host/db token=abc")

    try:
        boom()
    except RuntimeError as error:
        diagnostic = safe_diagnostic("summarize", error)
    encoded = diagnostic.model_dump_json()
    assert diagnostic.stage == "summarize"
    assert diagnostic.error_type == "RuntimeError"
    assert "secret" not in encoded and "password" not in encoded
    assert {item.file for item in diagnostic.error_location} == {
        "test_numeric_history_demo_release.py"}
    assert len(diagnostic.error_location) >= 1
    assert all(item.line >= 1 for item in diagnostic.error_location)
    assert all(
        "/" not in item.file and "\\" not in item.file
        for item in diagnostic.error_location
    )


def test_safe_diagnostic_accepts_a_process_failure_without_a_traceback():
    from scripts.numeric_history_demo_release import safe_diagnostic

    assert safe_diagnostic("stop_api", KeyboardInterrupt()).model_dump() == {
        "stage": "stop_api",
        "error_type": "KeyboardInterrupt",
        "error_location": [],
    }


def test_read_session_checks_treats_a_missing_record_as_none_not_a_pass(tmp_path):
    from scripts.numeric_history_demo_release import read_session_checks

    assert read_session_checks(tmp_path) is None


def test_read_session_checks_rejects_records_that_fail_the_closed_schema(tmp_path):
    from scripts import numeric_history_demo_release as release

    target = tmp_path / "session-checks.json"
    target.write_text(
        json.dumps({**_session_checks(), "token": "secret"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="^demo_session_checks_invalid$"):
        release.read_session_checks(tmp_path)
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="^demo_session_checks_invalid$"):
        release.read_session_checks(tmp_path)
    silent = _session_checks()
    silent["admission"]["non_owner_404"] = 0
    target.write_text(json.dumps(silent), encoding="utf-8")
    with pytest.raises(ValueError, match="^demo_session_checks_invalid$"):
        release.read_session_checks(tmp_path)


def test_read_session_checks_returns_the_closed_admission_outcomes(tmp_path):
    from scripts.numeric_history_demo_release import read_session_checks

    (tmp_path / "session-checks.json").write_text(
        json.dumps(_session_checks()), encoding="utf-8"
    )
    assert read_session_checks(tmp_path) == _session_checks()["admission"]


def _written_record(tmp_path, release, status=None):
    now = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    record = release.build_release_record(
        "2026-09-20-v1",
        {**identities(), "acceptance": {"acceptance_result_sha256": ACCEPTANCE_SHA}},
        "2" * 40,
        runtime(),
        now,
    )
    if status in {"running", "stopped", "failed"}:
        record = release.transition_release(
            record, "running", at=now + timedelta(minutes=1)
        )
    if status in {"stopped", "failed"}:
        record = release.transition_release(record, status, at=now + timedelta(hours=1))
    path = tmp_path / "release.json"
    path.write_text(json.dumps(record.model_dump(mode="json")), encoding="utf-8")
    return path


@pytest.mark.parametrize("status", ["starting", "running"])
def test_inspect_release_record_never_forges_a_stop_for_a_leftover_record(tmp_path, status):
    from scripts import numeric_history_demo_release as release

    path = _written_record(tmp_path, release, status)
    before = path.read_bytes()
    inspected = release.inspect_release_record(path)
    assert inspected["status"] == status
    assert inspected["unconfirmed_stop"] is True
    assert path.read_bytes() == before


@pytest.mark.parametrize("status", ["stopped", "failed"])
def test_inspect_release_record_reports_a_confirmed_terminal_record(tmp_path, status):
    from scripts import numeric_history_demo_release as release

    path = _written_record(tmp_path, release, status)
    inspected = release.inspect_release_record(path)
    assert inspected["status"] == status
    assert inspected["unconfirmed_stop"] is False


@pytest.mark.parametrize(
    "payload", ["{not json", json.dumps({"schema_version": "other.v1"})]
)
def test_inspect_release_record_rejects_an_unreadable_or_foreign_record(tmp_path, payload):
    from scripts.numeric_history_demo_release import inspect_release_record

    path = tmp_path / "release.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="^demo_release_record_unreadable$"):
        inspect_release_record(path)


def test_inspect_release_record_rejects_a_missing_file(tmp_path):
    from scripts.numeric_history_demo_release import inspect_release_record

    with pytest.raises(ValueError, match="^demo_release_record_unreadable$"):
        inspect_release_record(tmp_path / "absent.json")


def test_identity_matches_reports_each_recorded_identity_separately():
    from scripts import numeric_history_demo_release as release

    recorded = {
        "source": {
            "source_manifest_sha256": SOURCE_SHA,
            "data_content_sha256": SOURCE_DATA_SHA,
        },
        "legacy": {"bundle_sha256": LEGACY_SHA},
        "history": {"bundle_sha256": HISTORY_SHA},
        "renderer": {"manifest_sha256": RENDERER_SHA},
        "acceptance": {"acceptance_result_sha256": ACCEPTANCE_SHA},
        "git_commit": "2" * 40,
    }
    assert all(release.identity_matches(recorded, "2" * 40).values())
    assert release.identity_matches(recorded, "3" * 40) == {
        **{key: True for key in release.identity_matches(recorded, "2" * 40)},
        "git_commit_matches": False,
    }
    drifted = {**recorded, "history": {"bundle_sha256": "0" * 64}}
    assert release.identity_matches(drifted, "2" * 40)["history_bundle_matches"] is False
    assert release.identity_matches(drifted, "2" * 40)["source_matches"] is True


def test_identity_matches_never_assumes_a_match_without_a_record():
    from scripts import numeric_history_demo_release as release

    assert set(release.identity_matches(None, None).values()) == {False}
    assert set(release.identity_matches({}, "2" * 40).values()) == {False}


def test_current_commit_reads_head_and_fails_closed(monkeypatch):
    from scripts import numeric_history_demo_release as release

    monkeypatch.setattr(release, "_git", lambda *args, **kwargs: "2" * 40 + "\n")
    assert release._current_commit() == "2" * 40
    monkeypatch.setattr(
        release, "_git", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )
    assert release._current_commit() is None
    monkeypatch.setattr(release, "_git", lambda *args, **kwargs: "not-a-commit\n")
    assert release._current_commit() is None


# The exact event stream a real C-package report records, transcribed from
# outputs/numeric-history-acceptance/2026-09-20-v2/c-ad-report.json. Model tasks
# finish without an invocation; only the narrative has a started/finished pair.
REAL_REPORT_EVENTS = [
    ("phase_entered", "model_loading", None),
    ("phase_entered", "prediction", None),
    ("task_finished", "prediction", "ad.mmse.6m"),
    ("task_finished", "prediction", "ad.mmse.12m"),
    ("phase_entered", "standard_evidence", None),
    ("evidence_resolved", "standard_evidence", None),
    ("phase_entered", "rendering", None),
    ("invocation_started", "rendering", "report_narrative"),
    ("task_finished", "rendering", "report_narrative"),
    ("phase_entered", "persistence", None),
    ("terminal", "terminal", None),
]


def _real_audit(report_id=8):
    return [
        {
            "report_id": report_id,
            "event_seq": index,
            "event_kind": kind,
            "phase": phase,
            "task": task,
            "batch_id": "8b0f4f6e-0000-4000-8000-000000000001",
            "created_at": datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
            + timedelta(seconds=5 * index),
        }
        for index, (kind, phase, task) in enumerate(REAL_REPORT_EVENTS, start=1)
    ]


def test_release_metrics_close_a_narrative_invocation_among_model_task_finishes():
    """A real report finishes every model task; only the narrative is invoked."""
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    facts["audit"] = _real_audit()
    facts["jobs"] = [_fact(8, seconds=90)]
    facts["reports"] = [facts["reports"][0]]
    metrics = build_release_metrics(facts)
    assert metrics.llm_audit.model_dump() == {
        "invocation_started": 1,
        "task_finished": 3,
        "closed_reports": 1,
        "unclosed_reports": 0,
    }
    # The narrative runs during rendering, so rendering ends at the last
    # phase_entered before persistence rather than at the narrative finish.
    assert metrics.timings.rendering.samples == 1


def test_release_metrics_report_a_narrative_that_never_finished_as_unclosed():
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    audit = [
        event
        for event in _real_audit()
        if not (event["event_kind"] == "task_finished" and event["task"] == "report_narrative")
    ]
    for index, event in enumerate(audit, start=1):
        event["event_seq"] = index
    facts["audit"] = audit
    facts["jobs"] = [_fact(8, seconds=90)]
    facts["reports"] = [facts["reports"][0]]
    metrics = build_release_metrics(facts)
    assert metrics.llm_audit.model_dump() == {
        "invocation_started": 1,
        "task_finished": 2,
        "closed_reports": 0,
        "unclosed_reports": 1,
    }


def test_release_metrics_do_not_span_a_requeued_attempt_as_one_phase():
    """A re-queued report's attempts must not merge into one invented interval."""
    from scripts.numeric_history_demo_release import build_release_metrics

    facts = _facts()
    first = "8b0f4f6e-0000-4000-8000-000000000001"
    second = "8b0f4f6e-0000-4000-8000-000000000002"
    events = _real_audit()
    events = [
        event
        for event in events
        if event["event_kind"] == "phase_entered"
        and event["phase"] in ("model_loading", "prediction")
    ]
    for event in events:
        event["batch_id"] = first
    retry = [
        {
            **event,
            "event_seq": event["event_seq"] + 100,
            "batch_id": second,
            "created_at": event["created_at"] + timedelta(hours=1),
        }
        for event in events
    ]
    facts["audit"] = events + retry
    facts["jobs"] = [_fact(8, seconds=90)]
    facts["reports"] = [facts["reports"][0]]
    timings = build_release_metrics(facts).timings
    # Each attempt contributes its own short model_loading interval; the second
    # attempt's prediction phase is left unsampled rather than absorbing the hour.
    assert timings.model_loading.model_dump() == {
        "samples": 2, "total_ms": 10000, "max_ms": 5000}
    assert timings.prediction.samples == 0
