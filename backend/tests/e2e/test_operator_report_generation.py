"""Real UI, durable worker and PostgreSQL acceptance; only explicit local _test."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "outputs/operator-report-verification"


def headers(tokens):
    return {"Authorization": "Bearer " + tokens["a"]}


@pytest.mark.parametrize("disease,case_id", [("fatty_liver", 1), ("ad", 2)])
def test_real_page_generate_refresh_history_pdf(
    browser_page, operator_tokens, disease, case_id
):
    page = browser_page
    case = page.request.get(
        f"/api/v1/operator/longitudinal-cases/{case_id}",
        headers=headers(operator_tokens),
    ).json()
    page.add_init_script(
        'localStorage.setItem("token",' + json.dumps(operator_tokens["a"]) + ")"
    )
    page.goto("/operator")
    page.get_by_text("历史报告", exact=True).first.click()
    page.locator(".case-list__item").filter(
        has_text=case["anonymous_case_code"]
    ).click()
    with page.expect_response(
        lambda r: "/report-jobs" in r.url and r.request.method == "POST"
    ) as response:
        page.get_by_role("button", name="生成报告", exact=True).click()
    assert response.value.status == 202, response.value.text()
    report_id = response.value.json()["report_id"]
    expect(page).to_have_url(f"http://127.0.0.1:15173/operator?reportId={report_id}")
    page.reload()  # SSE closes; the accepted task remains durable.
    expect(page.locator("#section-11")).to_be_visible(timeout=60000)
    expect(page.get_by_role("button", name="下载 PDF")).to_be_enabled()
    page.screenshot(path=str(OUTPUT / f"{disease}-report.png"))
    detail = page.request.get(
        f"/api/v1/operator/reports/{report_id}", headers=headers(operator_tokens)
    ).json()
    assert detail["status"] == "completed"
    assert detail["integrity_status"] == "valid"
    assert len(detail["report_document"]["sections"]) == 11
    with page.expect_download() as download:
        page.get_by_role("button", name="下载 PDF").click()
    download.value.save_as(str(OUTPUT / f"{disease}-browser.pdf"))
    assert (OUTPUT / f"{disease}-browser.pdf").read_bytes().startswith(b"%PDF")
    page.get_by_role("button", name="返回病例", exact=True).click()
    page.goto(f"/operator?reportId={report_id}")
    expect(page.locator("#section-11")).to_be_visible(timeout=15000)
    forbidden = page.request.get(
        f"/api/v1/operator/reports/{report_id}/generation-status",
        headers={"Authorization": "Bearer " + operator_tokens["b"]},
    )
    assert forbidden.status == 404


@pytest.mark.parametrize("disease,disease_id", [("fatty_liver", 1), ("ad", 2)])
def test_ten_visits_all_catalog_generate(
    browser_page, operator_tokens, disease, disease_id
):
    page = browser_page
    auth = headers(operator_tokens)
    catalog = page.request.get(
        f"/api/v1/operator/diseases/{disease}/indicators", headers=auth
    ).json()["items"]
    payload = {
        "disease_id": disease_id,
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis" if disease == "fatty_liver" else "mci",
        "notes": "Automated software fixture: ten visits and every catalog indicator",
        "visits": [
            {
                "visit_date": f"2025-{month:02d}-01",
                "indicators": [
                    {
                        "name": item["code"],
                        "value": 1,
                        "unit": item["default_unit"] or item["allowed_units"][0],
                    }
                    for item in catalog
                ],
                "visit_context": {},
            }
            for month in range(1, 11)
        ],
    }
    created = page.request.post(
        "/api/v1/operator/longitudinal-cases",
        headers={**auth, "Idempotency-Key": str(uuid4())},
        data=payload,
    )
    assert created.ok, created.text()
    accepted = page.request.post(
        f"/api/v1/operator/longitudinal-cases/{created.json()['id']}/report-jobs",
        headers={**auth, "Idempotency-Key": str(uuid4())},
        data={},
    )
    assert accepted.status == 202, accepted.text()
    report_id = accepted.json()["report_id"]
    page.add_init_script(
        'localStorage.setItem("token",' + json.dumps(operator_tokens["a"]) + ")"
    )
    page.goto(f"/operator?reportId={report_id}")
    expect(page.locator("#section-11")).to_be_visible(timeout=60000)
    detail = page.request.get(
        f"/api/v1/operator/reports/{report_id}", headers=auth
    ).json()
    assert detail["integrity_status"] == "valid"
    visits = detail["input_snapshot"]["visits"]
    assert len(visits) == 10
    assert all(len(visit["indicators"]) == len(catalog) for visit in visits)


def test_same_key_replay_and_explicit_cancel(browser_page, operator_tokens):
    page = browser_page
    auth = headers(operator_tokens)
    key = str(uuid4())
    endpoint = "/api/v1/operator/longitudinal-cases/1/report-jobs"
    accepted = page.request.post(
        endpoint, headers={**auth, "Idempotency-Key": key}, data={}
    )
    assert accepted.status == 202
    first = accepted.json()
    replay = page.request.post(
        endpoint, headers={**auth, "Idempotency-Key": key}, data={}
    )
    assert replay.status == 202 and replay.json()["report_id"] == first["report_id"]
    report_id = first["report_id"]
    cancelled = page.request.post(
        f"/api/v1/operator/reports/{report_id}/cancel", headers=auth
    )
    assert cancelled.ok
    assert cancelled.json()["status"] in ("cancelled", "completed")
    replay = page.request.post(
        endpoint, headers={**auth, "Idempotency-Key": key}, data={}
    )
    assert replay.json()["report_id"] == report_id


def test_worker_kill_sweep_and_restart_continues_queued(browser_page, operator_tokens):
    import psutil
    from sqlalchemy import create_engine, text

    page = browser_page
    auth = headers(operator_tokens)
    # Stop the harness worker before admission so ownership of the next process is explicit.
    original = psutil.Process(int(os.environ["E2E_WORKER_PID"]))
    original.terminate()
    original.wait(10)
    accepted = page.request.post(
        "/api/v1/operator/longitudinal-cases/1/report-jobs",
        headers={**auth, "Idempotency-Key": str(uuid4())},
        data={},
    )
    assert accepted.status == 202, accepted.text()
    report_id = accepted.json()["report_id"]
    process = subprocess.Popen(
        [sys.executable, "-m", "app.workers.report_worker", "--once"],
        cwd=ROOT / "backend",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with engine.connect() as db:
                status = db.execute(
                    text(
                        "SELECT status FROM report_generation_jobs WHERE report_id=:id"
                    ),
                    {"id": report_id},
                ).scalar_one()
            if status == "running":
                break
            time.sleep(0.03)
        assert status == "running"
        process.kill()
        process.wait(5)
        time.sleep(7)  # Test-only lease=6 seconds; no automatic rerun.
        subprocess.run(
            [sys.executable, "-m", "app.workers.report_worker", "--sweep-only"],
            cwd=ROOT / "backend",
            check=True,
        )
        state = page.request.get(
            f"/api/v1/operator/reports/{report_id}/generation-status", headers=auth
        ).json()
        assert (
            state["status"] == "failed" and state["error_code"] == "worker_interrupted"
        )
        queued = page.request.post(
            "/api/v1/operator/longitudinal-cases/2/report-jobs",
            headers={**auth, "Idempotency-Key": str(uuid4())},
            data={},
        )
        assert queued.status == 202
        subprocess.run(
            [sys.executable, "-m", "app.workers.report_worker", "--once"],
            cwd=ROOT / "backend",
            check=True,
        )
        state = page.request.get(
            f"/api/v1/operator/reports/{queued.json()['report_id']}/generation-status",
            headers=auth,
        ).json()
        assert state["status"] == "completed"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(5)
        engine.dispose()
