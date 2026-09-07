"""Spawn isolation, bounded JSON IPC, deadline supervision and process trees."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import hashlib
import multiprocessing
import os
import time
import threading

from app.core.config import settings
from app.schemas.report_document import Publication
from app.services.report_generation_errors import safe_code

MAX_MESSAGE_BYTES = 8 * 1024 * 1024
PHASES = [
    "model_loading",
    "prediction",
    "standard_evidence",
    "rendering",
    "persistence",
]


@dataclass(frozen=True)
class ExecutionOutcome:
    publication: Publication | None
    code: str | None
    child_alive: bool
    phase: str | None = None


class _WindowsJob:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in [
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                ]
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api = api
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeError("process_tree_unavailable")
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self.close()
            raise RuntimeError("process_tree_unavailable")

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process.sentinel)):
            raise RuntimeError("process_tree_unavailable")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def managed_process_tree():
    job = _WindowsJob() if os.name == "nt" else None
    try:
        yield job
    finally:
        if job:
            job.close()


def stop_child(process):
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
    if process.is_alive():
        raise RuntimeError("child_termination_failed")


def _child_entry(target, payload, connection, gate, parent_pid):
    if os.name != "nt":
        # Linux supplements systemd KillMode=control-group for direct CLI runs.
        import ctypes
        import signal

        if hasattr(ctypes.CDLL(None), "prctl"):
            ctypes.CDLL(None).prctl(1, signal.SIGKILL)
            if os.getppid() != parent_pid:
                return
    if not gate.wait(timeout=10):
        connection.close()
        return

    def send_message(message):
        encoded = json.dumps(
            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ValueError("execution_protocol_invalid")
        connection.send_bytes(encoded)

    try:
        target(payload, send_message)
    except Exception as exc:
        try:
            send_message(
                {
                    "kind": "error",
                    "phase": "persistence",
                    "code": safe_code(getattr(exc, "code", None)),
                }
            )
        except (OSError, ValueError):
            pass
    finally:
        connection.close()


def _message(raw):
    value = json.loads(raw)
    if isinstance(value, dict) and value.get("kind") == "audit":
        from app.schemas.report_generation_audit import GenerationAuditEvent
        from app.services.report_generation_audit import encode_audit_event
        if (len(raw) > 262144 or set(value) != {"kind", "phase", "child_sequence", "audit"}
                or type(value["child_sequence"]) is not int or not 1 <= value["child_sequence"] <= 255):
            raise ValueError("execution_protocol_invalid")
        audit = GenerationAuditEvent.model_validate(value["audit"])
        if audit.phase != value["phase"] or audit.kind in ("terminal", "phase_entered"):
            raise ValueError("execution_protocol_invalid")
        value["audit"], _ = encode_audit_event(audit)
        return value
    if (
        not isinstance(value, dict)
        or set(value) - {"kind", "phase", "publication", "code"}
        or value.get("phase") not in PHASES
    ):
        raise ValueError("execution_protocol_invalid")
    kind = value.get("kind")
    if kind == "phase":
        if value.get("publication") is not None or value.get("code") is not None:
            raise ValueError("execution_protocol_invalid")
    elif kind == "publication":
        if (
            value["phase"] != "persistence"
            or value.get("code") is not None
            or not isinstance(value.get("publication"), dict)
        ):
            raise ValueError("execution_protocol_invalid")
    elif kind == "error":
        if value.get("publication") is not None or value.get("code") != safe_code(
            value.get("code")
        ):
            raise ValueError("execution_protocol_invalid")
    else:
        raise ValueError("execution_protocol_invalid")
    return value


def supervise_execution(
    target, payload, *, maximum_seconds, lease_check, on_phase, phase_limits, on_audit=None
):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    gate = ctx.Event()
    process = ctx.Process(
        target=_child_entry,
        args=(target, payload, send, gate, os.getpid()),
        daemon=False,
    )
    publication = None
    code = None
    audit_sequences = {}
    started = time.monotonic()
    phase_started = started
    phase = "model_loading"
    last_heartbeat = started
    watchdog_done = threading.Event()
    watchdog_expired = []
    phase_deadline = started + phase_limits.get(phase, maximum_seconds)
    with managed_process_tree() as tree:

        def enforce_deadline():
            # Database callbacks may block in the driver. Keep process termination
            # independent of those callbacks and of the worker's main loop.
            while not watchdog_done.wait(0.02):
                now = time.monotonic()
                reason = (
                    "run_timeout"
                    if now >= started + maximum_seconds
                    else "phase_timeout"
                    if now >= phase_deadline
                    else None
                )
                if reason:
                    watchdog_expired.append(reason)
                    if tree:
                        tree.close()
                    elif process.is_alive():
                        process.kill()
                    return

        watchdog = None
        try:
            process.start()
            send.close()
            if tree:
                tree.assign(process)
            watchdog = threading.Thread(target=enforce_deadline, daemon=True)
            watchdog.start()
            gate.set()
            if not lease_check():
                code = "lease_lost"
            while code is None and publication is None:
                now = time.monotonic()
                if watchdog_expired:
                    code = watchdog_expired[0]
                    break
                if now - started >= maximum_seconds:
                    code = "run_timeout"
                    break
                if now - phase_started >= phase_limits.get(phase, maximum_seconds):
                    code = "phase_timeout"
                    break
                if now - last_heartbeat >= settings.REPORT_JOB_HEARTBEAT_SECONDS:
                    if not lease_check():
                        code = "lease_lost"
                        break
                    last_heartbeat = now
                if receive.poll(
                    min(0.1, max(0.001, maximum_seconds - (now - started)))
                ):
                    try:
                        message = _message(receive.recv_bytes(MAX_MESSAGE_BYTES))
                    except (ValueError, TypeError, OSError, EOFError):
                        code = "execution_protocol_invalid"
                        break
                    next_phase = message["phase"]
                    if next_phase not in PHASES:
                        code = "execution_protocol_invalid"
                        break
                    if PHASES.index(next_phase) < PHASES.index(phase):
                        code = "execution_protocol_invalid"
                        break
                    if message["kind"] == "audit":
                        if next_phase != phase:
                            code = "execution_protocol_invalid"
                            break
                        sequence = message["child_sequence"]
                        digest = hashlib.sha256(json.dumps(message["audit"], sort_keys=True).encode()).hexdigest()
                        if sequence in audit_sequences:
                            if audit_sequences[sequence] != digest:
                                code = "execution_protocol_invalid"
                                break
                            continue
                        if sequence != len(audit_sequences) + 1:
                            code = "execution_protocol_invalid"
                            break
                        if on_audit is not None:
                            try:
                                accepted = on_audit(message["audit"])
                            except ValueError:
                                code = "execution_protocol_invalid"
                                break
                            if accepted is False:
                                code = "lease_lost"
                                break
                        audit_sequences[sequence] = digest
                        continue
                    if next_phase != phase:
                        if on_phase(next_phase) is False:
                            code = "lease_lost"
                            break
                        phase = next_phase
                        phase_started = time.monotonic()
                        phase_deadline = phase_started + phase_limits.get(
                            phase, maximum_seconds
                        )
                    if message["kind"] == "error":
                        code = message["code"]
                        break
                    if message["kind"] == "publication":
                        try:
                            publication = Publication.model_validate(
                                message["publication"]
                            )
                        except ValueError:
                            code = "execution_protocol_invalid"
                elif not process.is_alive():
                    code = "worker_interrupted"
                    break
        finally:
            watchdog_done.set()
            if watchdog:
                watchdog.join(timeout=1)
            if process.pid is not None:
                stop_child(process)
            receive.close()
            send.close()
    if watchdog_expired:
        publication = None
        code = watchdog_expired[0]
    alive = process.is_alive() if process.pid is not None else False
    process.close()
    return ExecutionOutcome(publication, code, alive, phase)
