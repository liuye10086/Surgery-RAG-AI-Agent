from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text


def _payload(disease_id=1):
    return {
        "disease_id": disease_id,
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis" if disease_id == 1 else "normal",
        "notes": "integration",
        "visits": [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "ALT" if disease_id == 1 else "MMSE", "value": 42 if disease_id == 1 else 28, "unit": "U/L" if disease_id == 1 else "分"}],
            }
        ],
    }


def test_create_is_idempotent_and_scoped_to_owner(client, db):
    key = str(uuid4())
    operator_a = client(1)
    first = operator_a.post("/api/v1/operator/longitudinal-cases", json=_payload(), headers={"Idempotency-Key": key})
    replay = operator_a.post("/api/v1/operator/longitudinal-cases", json=_payload(), headers={"Idempotency-Key": key})

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert operator_a.get("/api/v1/operator/longitudinal-cases").json()["total"] == 1
    assert client(2).get("/api/v1/operator/longitudinal-cases").json()["total"] == 0


def test_same_key_with_different_body_is_rejected_without_extra_case(client, db):
    key = str(uuid4())
    operator_a = client(1)
    assert operator_a.post("/api/v1/operator/longitudinal-cases", json=_payload(), headers={"Idempotency-Key": key}).status_code == 201
    altered = {**_payload(), "age": 57}
    response = operator_a.post("/api/v1/operator/longitudinal-cases", json=altered, headers={"Idempotency-Key": key})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_key_reused"
    assert db.execute(text("SELECT count(*) FROM operator_cases")).scalar_one() == 1


def test_aggregate_save_rolls_back_and_audit_is_immutable(client, db):
    operator_a = client(1)
    created = operator_a.post("/api/v1/operator/longitudinal-cases", json=_payload(), headers={"Idempotency-Key": str(uuid4())}).json()
    save_payload = {k: created[k] for k in ("age", "sex", "baseline_stage", "notes", "visits")}
    save_payload["age"] = 57
    save_payload["change_reason"] = "integration correction"
    response = operator_a.put(f"/api/v1/operator/longitudinal-cases/{created['id']}", json=save_payload)

    assert response.status_code == 200
    assert db.execute(text("SELECT count(*) FROM operator_case_change_logs WHERE action = 'profile_updated'")).scalar_one() == 1
    assert db.execute(text("SELECT age FROM operator_cases WHERE id = :id"), {"id": created["id"]}).scalar_one() == 57


def test_missing_idempotency_key_is_stable_error(client):
    response = client(1).post("/api/v1/operator/longitudinal-cases", json=_payload())
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "idempotency_key_missing"
