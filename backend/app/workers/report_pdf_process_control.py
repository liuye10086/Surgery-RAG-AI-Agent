"""Independent bounded PDF protocol and hard process-tree deadline."""

from dataclasses import dataclass
import json
import multiprocessing
import os
import signal
import threading
import time
from app.core.config import settings
from app.schemas.report_pdf_archive import PdfCandidate
from app.services.report_pdf_errors import safe_pdf_code
from app.services.report_pdf_repository import PDF_PHASES
from app.workers.report_process_control import managed_process_tree, stop_child


@dataclass(frozen=True)
class PdfOutcome:
    candidate: PdfCandidate | None
    code: str | None
    child_alive: bool
    phase: str


def _entry(target, payload, connection, gate, parent_pid):
    if os.name != "nt":
        os.setsid()
        # Close the startup race before the guardian can observe this new group.
        # Parent death before gate release must never start Chromium later.
        import ctypes
        runtime=ctypes.CDLL(None)
        if hasattr(runtime,'prctl'):
            runtime.prctl(1,signal.SIGKILL)
        if os.getppid()!=parent_pid:return
    if not gate.wait(10):
        return

    def send(value):
        raw = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(raw) > 65536:
            raise ValueError("pdf_protocol_invalid")
        connection.send_bytes(raw)

    try:
        target(payload, send)
    except Exception:
        try:
            send(
                {
                    "kind": "error",
                    "phase": "source_validation",
                    "code": "pdf_render_failed",
                }
            )
        except (ValueError, OSError):
            pass
    finally:
        connection.close()


def _linux_guardian(execution_pid, connection):
    # A separate sibling outlives an abruptly killed parent worker. EOF means
    # the only writer (the worker) disappeared; kill the dedicated process group.
    try:
        connection.recv_bytes()
    except (EOFError, OSError):
        try:
            os.killpg(execution_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    finally:
        connection.close()


def supervise_pdf(target, payload, *, maximum_seconds, lease_check, on_phase):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    gate = ctx.Event()
    child = ctx.Process(target=_entry, args=(target, payload, send, gate, os.getpid()))
    candidate = None
    code = None
    phase = "source_validation"
    done = threading.Event()
    expired = threading.Event()
    deadline = time.monotonic() + maximum_seconds
    guardian = None
    guardian_send = None
    watchdog = None
    with managed_process_tree() as tree:

        def kill_tree():
            if tree:
                tree.close()
            elif child.pid:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    if child.is_alive():
                        child.kill()

        def watch_deadline():
            if not done.wait(max(0, deadline - time.monotonic())):
                expired.set()
                kill_tree()

        try:
            child.start()
            send.close()
            if tree:
                tree.assign(child)
            else:
                guardian_receive, guardian_send = ctx.Pipe(duplex=False)
                guardian = ctx.Process(
                    target=_linux_guardian, args=(child.pid, guardian_receive)
                )
                guardian.start()
                guardian_receive.close()
            watchdog = threading.Thread(target=watch_deadline, daemon=True)
            watchdog.start()
            gate.set()
            heartbeat = time.monotonic()
            if not lease_check():
                code = "pdf_lease_lost"
            while code is None and candidate is None:
                now = time.monotonic()
                if expired.is_set() or now >= deadline:
                    code = "pdf_render_timeout"
                    break
                if now - heartbeat >= settings.REPORT_PDF_HEARTBEAT_SECONDS:
                    if not lease_check():
                        code = "pdf_lease_lost"
                        break
                    heartbeat = now
                if receive.poll(min(0.1, max(0.001, deadline - now))):
                    try:
                        message = json.loads(receive.recv_bytes(65536))
                        if (
                            not isinstance(message, dict)
                            or message.get("phase") not in PDF_PHASES[1:-1]
                        ):
                            raise ValueError()
                        next_phase = message["phase"]
                        kind = message.get("kind")
                        required = {"phase", "kind"} | (
                            {"candidate"}
                            if kind == "candidate"
                            else {"code"} if kind == "error" else set()
                        )
                        if (
                            set(message) != required
                            or kind not in ("candidate", "phase", "error")
                            or PDF_PHASES.index(next_phase) < PDF_PHASES.index(phase)
                        ):
                            raise ValueError()
                        if next_phase != phase:
                            if on_phase(next_phase) is False:
                                code = "pdf_lease_lost"
                                break
                            phase = next_phase
                        if kind == "candidate":
                            if phase != "publish":
                                raise ValueError()
                            candidate = PdfCandidate.model_validate(
                                message["candidate"]
                            )
                        elif kind == "error":
                            if message["code"] != safe_pdf_code(message["code"]):
                                raise ValueError()
                            code = message["code"]
                    except (ValueError, TypeError, OSError, EOFError):
                        code = "pdf_render_failed"
                elif not child.is_alive():
                    code = "pdf_worker_interrupted"
        finally:
            done.set()
            if watchdog:
                watchdog.join(1)
            if child.pid is not None:
                kill_tree()
                stop_child(child)
            if guardian_send:
                try:
                    guardian_send.send_bytes(b"done")
                except OSError:
                    pass
                guardian_send.close()
            if guardian:
                guardian.join(2)
                if guardian.is_alive():
                    guardian.kill()
                    guardian.join(2)
                guardian.close()
            receive.close()
            send.close()
    alive = child.is_alive() if child.pid is not None else False
    child.close()
    if expired.is_set():
        candidate = None
        code = "pdf_render_timeout"
    return PdfOutcome(candidate, code, alive, phase)
