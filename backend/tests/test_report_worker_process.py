import time
from app.workers.report_process_control import supervise_execution


def blocked_target(payload, send_message):
    send_message({"kind": "phase", "phase": "prediction"})
    time.sleep(30)


def bad_target(payload, send_message):
    send_message({"kind": "publication", "phase": "prediction", "code": "private"})


def failed_standard_target(payload, send_message):
    send_message({"kind": "phase", "phase": "standard_evidence"})
    send_message({"kind": "error", "phase": "standard_evidence", "code": "standard_query_failed"})


def audit_target(payload, send_message):
    send_message({"kind": "phase", "phase": "prediction"})
    message = {"kind": "audit", "phase": "prediction", "child_sequence": 1,
               "audit": {"kind": "input_prepared", "phase": "prediction", "task": "test_task"}}
    send_message(message)
    send_message(message)
    send_message({"kind": "error", "phase": "prediction", "code": "prediction_failed"})


def test_error_phase_is_preserved():
    result = supervise_execution(failed_standard_target, {}, maximum_seconds=10,
                                 lease_check=lambda: True, on_phase=lambda _: True, phase_limits={})
    assert result.phase == "standard_evidence"
    assert result.code == "standard_query_failed"


def test_duplicate_child_audit_is_acknowledged_once():
    events = []
    result = supervise_execution(audit_target, {}, maximum_seconds=10,
                                 lease_check=lambda: True, on_phase=lambda _: True, phase_limits={},
                                 on_audit=lambda event: events.append(event) or True)
    assert result.code == "prediction_failed"
    assert len(events) == 1


def test_timeout_terminates_real_child():
    result = supervise_execution(
        blocked_target,
        {},
        maximum_seconds=0.3,
        lease_check=lambda: True,
        on_phase=lambda phase: True,
        phase_limits={"prediction": 0.3},
    )
    assert result.code == "run_timeout"
    assert result.child_alive is False


def test_blocked_heartbeat_cannot_keep_execution_alive_past_deadline(tmp_path):
    import psutil

    path = tmp_path / "deadline-child.pid"

    def blocked_heartbeat():
        deadline = time.monotonic() + 2
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert path.exists()
        child = psutil.Process(int(path.read_text()))
        # Simulate a DB connection stall beyond the execution hard deadline.
        child.wait(timeout=4)
        assert not child.is_running()
        return True

    result = supervise_execution(
        pid_target,
        {"pid_file": str(path)},
        maximum_seconds=3,
        lease_check=blocked_heartbeat,
        on_phase=lambda phase: True,
        phase_limits={},
    )
    assert result.code == "run_timeout" and not result.child_alive


def test_invalid_protocol_cannot_publish():
    result = supervise_execution(
        bad_target,
        {},
        maximum_seconds=10,
        lease_check=lambda: True,
        on_phase=lambda phase: True,
        phase_limits={"prediction": 5},
    )
    assert result.code == "execution_protocol_invalid"
    assert result.publication is None


def repeated_phase_target(payload, send_message):
    for _ in range(100):
        send_message({"kind": "phase", "phase": "prediction"})
        time.sleep(0.05)


def pid_target(payload, send_message):
    import os
    from pathlib import Path

    Path(payload["pid_file"]).write_text(str(os.getpid()))
    time.sleep(60)


def parent_target(pid_file):
    supervise_execution(
        pid_target,
        {"pid_file": pid_file},
        maximum_seconds=50,
        lease_check=lambda: True,
        on_phase=lambda phase: True,
        phase_limits={},
    )


def test_repeated_phase_does_not_reset_deadline():
    result = supervise_execution(
        repeated_phase_target,
        {},
        maximum_seconds=15,
        lease_check=lambda: True,
        on_phase=lambda phase: True,
        phase_limits={"prediction": 0.3},
    )
    assert result.code == "phase_timeout"
    assert not result.child_alive


def test_parent_kill_terminates_child(tmp_path):
    import multiprocessing
    import psutil

    path = tmp_path / "child.pid"
    parent = multiprocessing.get_context("spawn").Process(
        target=parent_target, args=(str(path),)
    )
    parent.start()
    child = None
    try:
        deadline = time.monotonic() + 20
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert path.exists(), "child did not start"
        child = psutil.Process(int(path.read_text()))
        parent.kill()
        parent.join(5)
        child.wait(timeout=10)
        assert not child.is_running()
    finally:
        if parent.is_alive():
            parent.kill()
            parent.join(5)
        if child and child.is_running():
            child.kill()
        parent.close()


def huge_target(payload, send_message):
    send_message(
        {
            "kind": "publication",
            "phase": "persistence",
            "publication": {"oversized": "x" * (9 * 1024 * 1024)},
        }
    )


def test_lost_lease_stops_real_execution():
    result = supervise_execution(
        blocked_target,
        {},
        maximum_seconds=10,
        lease_check=lambda: False,
        on_phase=lambda phase: True,
        phase_limits={},
    )
    assert result.code == "lease_lost" and not result.child_alive


def test_oversized_publication_is_never_deserialized():
    result = supervise_execution(
        huge_target,
        {},
        maximum_seconds=10,
        lease_check=lambda: True,
        on_phase=lambda phase: True,
        phase_limits={},
    )
    assert result.publication is None and not result.child_alive
