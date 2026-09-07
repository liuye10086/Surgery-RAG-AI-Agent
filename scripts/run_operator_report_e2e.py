"""Own and clean up the isolated E2E API, worker and Vite process trees."""

import os
import subprocess
import sys
import time
import threading
import json
import urllib.request
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main():
    from scripts.seed_operator_report_e2e import require_test_database

    url = os.environ.get("TEST_DATABASE_URL", "")
    require_test_database(url)
    manifest = os.environ.get("REPORT_TEST_RENDERER_MANIFEST", "")
    if not Path(manifest).is_file():
        raise RuntimeError("explicit_built_renderer_manifest_required")
    archive_root = ROOT / "outputs/operator-report-archive-verification" / ("e2e-"+str(uuid4()))
    archive_root.mkdir(parents=True)
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "backend"))),
        "PYTHONUTF8": "1",
        "OPENAI_API_KEY": "test-only-not-a-real-key",
        "DEEPSEEK_API_KEY": "test-only-not-a-real-key",
        "REPORT_HISTORY_CURSOR_SECRET": "isolated-e2e-history-cursor-secret-32-bytes",
        "REPORT_PDF_ENABLED": "true",
        "REPORT_PDF_ACCEPTING": "true",
        "REPORT_PDF_RENDERER_MANIFEST": manifest,
        "REPORT_ARCHIVE_ROOT": str(archive_root),
        "REPORT_JOBS_ENABLED": "true",
        "REPORT_JOBS_ACCEPTING": "true",
        "REPORT_JOB_LEASE_SECONDS": "6",
        "REPORT_JOB_HEARTBEAT_SECONDS": "2",
        "REPORT_JOB_SWEEP_SECONDS": "3",
        "E2E_BASE_URL": "http://127.0.0.1:15173",
        "E2E_API_PROXY": "http://127.0.0.1:18060",
    }
    # Parent imports below must use exactly the same isolated settings.
    previous = dict(os.environ)
    os.environ.update(env)
    processes = {}
    logs = []
    output = ROOT / "outputs/operator-report-verification"
    output.mkdir(parents=True, exist_ok=True)
    import psutil

    stopped = threading.Event()
    memory = {"api_peak_mib": 0, "worker_tree_peak_mib": 0, "frontend_peak_mib": 0}

    def sample_memory():
        while not stopped.wait(0.25):
            for name, process in list(processes.items()):
                try:
                    parent = psutil.Process(process.pid)
                    size = parent.memory_info().rss
                    for child in parent.children(recursive=True):
                        try:
                            size += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                    memory[name + "_peak_mib"] = max(
                        memory.get(name + "_peak_mib", 0), round(size / 1024**2, 1)
                    )
                except psutil.NoSuchProcess:
                    pass

    monitor = threading.Thread(target=sample_memory, daemon=True)
    monitor.start()
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
        )
        from app.db.session import SessionLocal
        from scripts.seed_operator_report_e2e import seed

        case_ids = seed(SessionLocal)
        from app.core.config import settings
        from app.core.security import create_access_token

        for label, user_id in (("A", 1), ("B", 2)):
            env["E2E_OPERATOR_TOKEN_" + label] = create_access_token(
                {"sub": str(user_id)}, settings.JWT_SECRET, settings.JWT_ALGORITHM
            )
        for name, command, cwd in (
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.tests.e2e.report_test_server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18060",
                ],
                ROOT,
            ),
            (
                "worker",
                [sys.executable, "-m", "app.workers.report_worker"],
                ROOT / "backend",
            ),
            ("pdf_worker", [sys.executable, "-m", "app.workers.report_pdf_worker"], ROOT / "backend"),
            ("cleanup", [sys.executable, "scripts/manage_report_pdf_archives.py", "cleanup", "--sweep"], ROOT),
            (
                "frontend",
                [
                    "node",
                    str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "15173",
                    "--strictPort",
                ],
                ROOT / "frontend",
            ),
        ):
            log = (output / f"{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            processes[name] = process
            if name == "worker":
                env["E2E_WORKER_PID"] = str(process.pid)
        for endpoint in ("http://127.0.0.1:18060/health", "http://127.0.0.1:15173"):
            deadline = time.monotonic() + 60
            while True:
                if any(p.poll() is not None for p in processes.values()):
                    raise RuntimeError("test_service_exited")
                try:
                    with urllib.request.urlopen(endpoint, timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("test_service_start_timeout")
                time.sleep(0.3)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "backend/tests/e2e/test_operator_case_workspace.py",
            "backend/tests/e2e/test_operator_report_generation.py",
            "backend/tests/e2e/test_operator_history_pdf_archive.py",
            "-q",
            "--tb=short",
        ]
        result = subprocess.run(command, cwd=ROOT, env=env).returncode
        if result == 0:
            result = subprocess.run([sys.executable, "scripts/verify_operator_report_pdf.py", "--output-dir", str(ROOT / "outputs/operator-history-pdf/pdf")], cwd=ROOT, env=env).returncode
        return result
    finally:
        stopped.set()
        monitor.join(2)
        (output / "memory.json").write_text(
            json.dumps(memory, sort_keys=True), encoding="utf-8"
        )
        for process in reversed(list(processes.values())):
            try:
                parent = psutil.Process(process.pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                parent.terminate()
                _, alive = psutil.wait_procs([parent, *children], timeout=5)
                for item in alive:
                    try:
                        item.kill()
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
        for log in logs:
            log.close()
        os.environ.clear()
        os.environ.update(previous)


if __name__ == "__main__":
    raise SystemExit(main())
