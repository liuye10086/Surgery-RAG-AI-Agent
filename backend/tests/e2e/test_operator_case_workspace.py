from __future__ import annotations

from uuid import uuid4


def _payload():
    return {
        "disease_id": 1,
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis",
        "notes": "e2e",
        "visits": [{
            "visit_date": "2026-01-01",
            "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
        }],
    }


def test_operator_workspace_create_save_and_owner_isolation(browser_page, operator_tokens):
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
    assert page.request.get(
        "/api/v1/operator/reports",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"analysis_type": "longitudinal_predictive"},
    ).json()["total"] == 0

    save_payload = {k: case[k] for k in ("age", "sex", "baseline_stage", "notes", "visits")}
    save_payload.update(age=57, change_reason="e2e correction")
    saved = page.request.put(
        f"/api/v1/operator/longitudinal-cases/{case['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
        data=save_payload,
    )
    assert saved.ok
    assert saved.json()["age"] == 57
    assert page.request.get(
        "/api/v1/operator/longitudinal-cases",
        headers={"Authorization": f"Bearer {token_b}"},
    ).json()["total"] == 0
    assert page.request.get(
        f"/api/v1/operator/longitudinal-cases/{case['id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    ).status == 404
