"""History and original lifetime on the isolated, real API and PDF worker."""

import hashlib
import json
import os
import time
import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("disease,case_id", [("fatty_liver", 1), ("ad", 2)])
def test_history_survives_case_change_and_deletion(
    browser_page, operator_tokens, disease, case_id
):
    page = browser_page
    auth = {"Authorization": "Bearer " + operator_tokens["a"]}
    rows = page.request.get(
        "/api/v1/operator/report-history",
        headers=auth,
        params={"disease_code": disease, "status": "completed"},
    ).json()["items"]
    ready = [r for r in rows if r["pdf_status"] == "ready"]
    assert ready
    item = ready[0]
    report_id = item["id"]
    endpoint = f"/api/v1/operator/reports/{report_id}"
    first = page.request.get(endpoint + "/download", headers=auth)
    assert first.ok
    digest = hashlib.sha256(first.body()).hexdigest()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE operator_cases SET notes='test fixture changed after publication' WHERE id=:id"
                ),
                {"id": case_id},
            )
            db.execute(
                text("UPDATE diseases SET operator_enabled=false WHERE code=:code"),
                {"code": disease},
            )
        page.add_init_script(
            'localStorage.setItem("token",' + json.dumps(operator_tokens["a"]) + ")"
        )
        page.goto("/operator")
        page.get_by_role("button", name="历史报告", exact=True).click()
        expect(page.locator("#history-title")).to_be_visible(timeout=5000)
        page.get_by_label("病种", exact=True).select_option(disease)
        page.get_by_label("病例编号", exact=True).fill(item["anonymous_case_code"])
        page.get_by_role("button", name="筛选", exact=True).click()
        row = page.locator(f'.history-row[data-report-id="{report_id}"]')
        expect(row).to_have_count(1)
        row.locator(".open-report").click()
        expect(page.get_by_role("button", name="下载 PDF", exact=True)).to_be_enabled(
            timeout=15000
        )
        assert (
            hashlib.sha256(
                page.request.get(endpoint + "/download", headers=auth).body()
            ).hexdigest()
            == digest
        )
        # Re-enable mutations after proving reads work while the disease is disabled.
        with engine.begin() as db:
            db.execute(text('UPDATE diseases SET operator_enabled=true WHERE code=:code'),{'code':disease})
        # Case deletion uses the actual owned API; saved report and bytes remain.
        deleted = page.request.delete(
            f"/api/v1/operator/longitudinal-cases/{case_id}", headers=auth
        )
        assert deleted.ok, deleted.text()
        assert (
            page.request.get(endpoint, headers=auth).json()["integrity_status"]
            == "valid"
        )
        assert (
            hashlib.sha256(
                page.request.get(endpoint + "/download", headers=auth).body()
            ).hexdigest()
            == digest
        )
        assert (
            page.request.get(
                endpoint + "/download",
                headers={"Authorization": "Bearer " + operator_tokens["b"]},
            ).status
            == 404
        )
        page.get_by_role("button", name="返回", exact=True).click()
        expect(page.get_by_label("病种", exact=True)).to_have_value(disease)
        row.get_by_role("button", name="删除报告", exact=True).click()
        page.get_by_role("button", name="删除", exact=True).click()
        expect(row).to_have_count(0)
        assert page.request.get(endpoint + "/download", headers=auth).status == 404
        with engine.begin() as db:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM report_pdf_archives WHERE report_id=:id"
                    ),
                    {"id": report_id},
                ).scalar_one()
                == 0
            )
            db.execute(
                text(
                    "UPDATE report_file_cleanup_tasks SET next_attempt_at=clock_timestamp(),not_before_final_check=clock_timestamp()-interval '1 second' WHERE report_id_snapshot=:id"
                ),
                {"id": report_id},
            )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with engine.connect() as db:
                remaining = db.execute(
                    text(
                        "SELECT count(*) FROM report_file_cleanup_tasks WHERE report_id_snapshot=:id AND state!='done'"
                    ),
                    {"id": report_id},
                ).scalar_one()
            if not remaining:
                break
            time.sleep(0.1)
        assert remaining == 0
    finally:
        with engine.begin() as db:
            db.execute(
                text("UPDATE diseases SET operator_enabled=true WHERE code=:code"),
                {"code": disease},
            )
        engine.dispose()
