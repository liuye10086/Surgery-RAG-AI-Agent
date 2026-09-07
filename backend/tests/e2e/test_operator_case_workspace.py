from __future__ import annotations

import json
from uuid import uuid4

import pytest


def _payload(disease_id=1, disease_code="fatty_liver"):
    is_fatty = disease_code == "fatty_liver"
    return {
        "disease_id": disease_id,
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis" if is_fatty else "mci",
        "notes": "e2e",
        "visits": [
            {
                "visit_date": "2026-01-01",
                "indicators": [
                    {
                        "name": "ALT" if is_fatty else "MMSE",
                        "value": 42 if is_fatty else 28,
                        "unit": "U/L" if is_fatty else "分",
                    }
                ],
                "visit_context": {"source_type": "lab" if is_fatty else "assessment"},
            }
        ],
    }


def _editable_visits(visits):
    return [
        {
            "visit_date": visit["visit_date"],
            "indicators": visit["indicators"],
            "notes": visit.get("notes"),
            "visit_context": visit.get("visit_context", {}),
        }
        for visit in visits
    ]


def test_operator_workspace_create_save_and_owner_isolation(
    browser_page, operator_tokens
):
    page = browser_page
    token_a = operator_tokens["a"]
    token_b = operator_tokens["b"]
    key = str(uuid4())
    created = page.request.post(
        "/api/v1/operator/longitudinal-cases",
        headers={"Authorization": f"Bearer {token_a}", "Idempotency-Key": key},
        data=_payload(),
    )
    assert created.ok
    case = created.json()
    assert case["anonymous_case_code"]
    assert (
        page.request.get(
            "/api/v1/operator/reports",
            headers={"Authorization": f"Bearer {token_a}"},
            params={"analysis_type": "longitudinal_predictive"},
        ).json()["total"]
        == 0
    )

    save_payload = {k: case[k] for k in ("age", "sex", "baseline_stage", "notes")}
    save_payload["visits"] = _editable_visits(case["visits"])
    save_payload.update(age=57, change_reason="e2e correction")
    saved = page.request.put(
        f"/api/v1/operator/longitudinal-cases/{case['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
        data=save_payload,
    )
    assert saved.ok, saved.text()
    assert saved.json()["age"] == 57
    assert (
        page.request.get(
            "/api/v1/operator/longitudinal-cases",
            headers={"Authorization": f"Bearer {token_b}"},
        ).json()["total"]
        == 0
    )
    assert (
        page.request.get(
            f"/api/v1/operator/longitudinal-cases/{case['id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        ).status
        == 404
    )


@pytest.mark.parametrize("disease_code", ["fatty_liver", "ad"])
def test_dual_disease_catalog_and_three_visit_aggregate(
    browser_page, operator_tokens, disease_code
):
    page = browser_page
    headers = {"Authorization": f"Bearer {operator_tokens['a']}"}
    diseases = page.request.get("/api/v1/operator/diseases", headers=headers).json()
    disease = next(item for item in diseases if item["code"] == disease_code)
    catalog = page.request.get(
        f"/api/v1/operator/diseases/{disease_code}/indicators",
        headers=headers,
    )
    assert catalog.ok
    assert catalog.json()["catalog_version"]

    created = page.request.post(
        "/api/v1/operator/longitudinal-cases",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        data=_payload(disease["id"], disease_code),
    )
    assert created.ok
    case = created.json()
    seed = case["visits"][0]
    visits = [
        {
            **seed,
            "visit_date": day,
            "visit_context": {
                **seed.get("visit_context", {}),
                "facility_name": f"E2E-{day}",
            },
        }
        for day in ("2026-03-01", "2026-01-01", "2026-02-01")
    ]
    for visit in visits:
        for server_field in (
            "id",
            "case_id",
            "visit_index",
            "created_at",
            "updated_at",
        ):
            visit.pop(server_field, None)
    saved = page.request.put(
        f"/api/v1/operator/longitudinal-cases/{case['id']}",
        headers=headers,
        data={
            "age": case["age"],
            "sex": case["sex"],
            "baseline_stage": case["baseline_stage"],
            "notes": case["notes"],
            "visits": visits,
            "change_reason": "E2E 补录访视",
        },
    )
    assert saved.ok, saved.text()
    assert [item["visit_index"] for item in saved.json()["visits"]] == [1, 2, 3]


def test_browser_editor_loads_disease_catalog_and_null_safe_value(
    browser_page, operator_tokens
):
    page = browser_page
    page.add_init_script(
        f"window.localStorage.setItem('token', {json.dumps(operator_tokens['a'])})"
    )
    page.goto("/operator")
    page.get_by_role("button", name="新建病例").first.click()
    disease_select = page.locator(".profile-grid select").first
    with page.expect_response(
        lambda response: (
            "/operator/diseases/fatty_liver/indicators" in response.url
            and response.status == 200
        )
    ):
        disease_select.select_option(label="脂肪肝")
    indicator_select = page.locator('select[aria-label="指标名称"]').first
    indicator_select.select_option("alt")
    assert page.locator('select[aria-label="指标单位"]').first.input_value() == "U/L"
    value_input = page.locator('input[aria-label="指标值"]').first
    value_input.fill("")
    assert value_input.input_value() == ""
