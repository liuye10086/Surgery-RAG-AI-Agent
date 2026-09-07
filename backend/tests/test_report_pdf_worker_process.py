import time
from app.workers.report_pdf_process_control import supervise_pdf


def blocked_pdf(payload, send):
    send({"kind": "phase", "phase": "print"})
    time.sleep(60)


def invalid_pdf(payload, send):
    send({"kind": "candidate", "phase": "publish", "candidate": {"bytes": "x" * 70000}})


def test_pdf_deadline_stops_real_child():
    result = supervise_pdf(
        blocked_pdf,
        {},
        maximum_seconds=0.5,
        lease_check=lambda: True,
        on_phase=lambda _: True,
    )
    assert result.code == "pdf_render_timeout"
    assert not result.child_alive


def test_pdf_protocol_rejects_large_candidate():
    result = supervise_pdf(
        invalid_pdf,
        {},
        maximum_seconds=10,
        lease_check=lambda: True,
        on_phase=lambda _: True,
    )
    assert result.candidate is None
    assert not result.child_alive


def real_browser(payload, send):
    import os, json
    from pathlib import Path
    import psutil
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<p>process ownership test</p>")
        Path(payload["pids"]).write_text(
            json.dumps(
                [
                    os.getpid(),
                    *[p.pid for p in psutil.Process().children(recursive=True)],
                ]
            )
        )
        send({"kind": "phase", "phase": "print"})
        time.sleep(60)
        browser.close()


def browser_supervisor(path):
    supervise_pdf(
        real_browser,
        {"pids": path},
        maximum_seconds=45,
        lease_check=lambda: True,
        on_phase=lambda _: True,
    )


def test_killing_parent_worker_terminates_real_chromium_tree(tmp_path):
    import json, multiprocessing, psutil

    path = tmp_path / "owned-pids.json"
    process = multiprocessing.get_context("spawn").Process(
        target=browser_supervisor, args=(str(path),)
    )
    pids = []
    try:
        process.start()
        deadline = time.monotonic() + 20
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert path.exists(), "real browser did not start"
        pids = json.loads(path.read_text())
        assert len(pids) >= 3
        process.kill()
        process.join(5)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            alive = []
            for pid in pids:
                try:
                    if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                        alive.append(pid)
                except psutil.NoSuchProcess:
                    pass
            if not alive:
                break
            time.sleep(0.05)
        assert not alive
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        process.close()
        for pid in pids:
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass
