from scripts.check_operator_report_generation_readonly import evaluate_gate


def test_postflight_rejects_expired_jobs_and_missing_worker():
    result = evaluate_gate(
        dict(
            schema_ready=True,
            context_invalid=0,
            terminal_mismatch=0,
            expired_jobs=1,
            legacy_generating=0,
            worker_ready=False,
        ),
        "postflight",
    )
    assert result["status"] == "FAIL"
    assert set(result["failed_checks"]) == {"expired_jobs", "worker_ready"}


def test_preflight_allows_pending_migration_but_never_legacy_running():
    checks = dict(
        schema_ready=False,
        context_invalid=0,
        terminal_mismatch=0,
        expired_jobs=0,
        legacy_generating=0,
    )
    assert evaluate_gate(checks, "preflight")["status"] == "PASS"
    checks["legacy_generating"] = 1
    assert evaluate_gate(checks, "preflight")["failed_checks"] == ["legacy_generating"]


def test_postflight_rejects_early_acceptance_and_tampered_document():
    checks = dict(
        schema_ready=True,
        context_invalid=0,
        terminal_mismatch=0,
        expired_jobs=0,
        legacy_generating=0,
        worker_ready=True,
        accepting=True,
        document_invalid=1,
    )
    assert set(evaluate_gate(checks, "postflight")["failed_checks"]) == {
        "accepting",
        "document_invalid",
    }
