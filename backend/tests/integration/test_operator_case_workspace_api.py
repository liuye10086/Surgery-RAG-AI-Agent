from __future__ import annotations

from uuid import uuid4
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
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
                "indicators": [
                    {
                        "name": "ALT" if disease_id == 1 else "MMSE",
                        "value": 42 if disease_id == 1 else 28,
                        "unit": "U/L" if disease_id == 1 else "分",
                    }
                ],
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


def test_create_is_idempotent_and_scoped_to_owner(client, db):
    key = str(uuid4())
    operator_a = client(1)
    first = operator_a.post(
        "/api/v1/operator/longitudinal-cases",
        json=_payload(),
        headers={"Idempotency-Key": key},
    )
    replay = operator_a.post(
        "/api/v1/operator/longitudinal-cases",
        json=_payload(),
        headers={"Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert operator_a.get("/api/v1/operator/longitudinal-cases").json()["total"] == 1
    assert client(2).get("/api/v1/operator/longitudinal-cases").json()["total"] == 0


def test_same_key_with_different_body_is_rejected_without_extra_case(client, db):
    key = str(uuid4())
    operator_a = client(1)
    assert (
        operator_a.post(
            "/api/v1/operator/longitudinal-cases",
            json=_payload(),
            headers={"Idempotency-Key": key},
        ).status_code
        == 201
    )
    altered = {**_payload(), "age": 57}
    response = operator_a.post(
        "/api/v1/operator/longitudinal-cases",
        json=altered,
        headers={"Idempotency-Key": key},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_key_reused"
    assert db.execute(text("SELECT count(*) FROM operator_cases")).scalar_one() == 1


def test_aggregate_save_rolls_back_and_audit_is_immutable(client, db):
    operator_a = client(1)
    created = operator_a.post(
        "/api/v1/operator/longitudinal-cases",
        json=_payload(),
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    save_payload = {k: created[k] for k in ("age", "sex", "baseline_stage", "notes")}
    save_payload["visits"] = _editable_visits(created["visits"])
    save_payload["age"] = 57
    save_payload["change_reason"] = "integration correction"
    response = operator_a.put(
        f"/api/v1/operator/longitudinal-cases/{created['id']}", json=save_payload
    )

    assert response.status_code == 200
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM operator_case_change_logs WHERE action = 'profile_updated'"
            )
        ).scalar_one()
        == 1
    )
    assert (
        db.execute(
            text("SELECT age FROM operator_cases WHERE id = :id"), {"id": created["id"]}
        ).scalar_one()
        == 57
    )


def test_missing_idempotency_key_is_stable_error(client):
    response = client(1).post("/api/v1/operator/longitudinal-cases", json=_payload())
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "idempotency_key_missing"


@pytest.mark.parametrize(
    ("disease_id", "disease_code", "stage", "indicator", "value", "unit"),
    [
        (1, "fatty_liver", "pre_cirrhosis", "ALT", 42, "u/l"),
        (2, "ad", "mci", "MMSE", 28, "分"),
    ],
)
def test_dual_disease_append_to_three_visits_with_canonical_context(
    client,
    db,
    disease_id,
    disease_code,
    stage,
    indicator,
    value,
    unit,
):
    operator = client(1)
    catalog = operator.get(f"/api/v1/operator/diseases/{disease_code}/indicators")
    assert catalog.status_code == 200
    assert catalog.json()["catalog_version"]

    payload = {
        "disease_id": disease_id,
        "age": 56,
        "sex": "male",
        "baseline_stage": stage,
        "notes": None,
        "visits": [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": indicator, "value": value, "unit": unit}],
                "visit_context": {"source_type": "lab", "facility_name": "中心实验室"},
            }
        ],
    }
    created_response = operator.post(
        "/api/v1/operator/longitudinal-cases",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert len(created["visits"]) == 1
    canonical = created["visits"][0]["indicators"][0]
    assert canonical["name"] == ("alt" if disease_code == "fatty_liver" else "mmse")
    assert canonical["unit"] == ("U/L" if disease_code == "fatty_liver" else "分")
    assert created["visits"][0]["visit_context"]["source_type"] == "lab"

    visits = []
    for day in ("2026-03-01", "2026-01-01", "2026-02-01"):
        visits.append(
            {
                "visit_date": day,
                "indicators": [{"name": indicator, "value": value, "unit": unit}],
                "visit_context": {
                    "source_type": "lab",
                    "facility_name": f"实验室-{day}",
                },
            }
        )
    saved_response = operator.put(
        f"/api/v1/operator/longitudinal-cases/{created['id']}",
        json={
            "age": created["age"],
            "sex": created["sex"],
            "baseline_stage": created["baseline_stage"],
            "notes": created["notes"],
            "visits": visits,
            "change_reason": "补录纵向访视",
        },
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    assert [visit["visit_date"] for visit in saved["visits"]] == [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert [visit["visit_index"] for visit in saved["visits"]] == [1, 2, 3]
    assert saved["visits"][2]["visit_context"]["facility_name"] == "实验室-2026-03-01"

    readiness = operator.get(
        f"/api/v1/operator/longitudinal-cases/{created['id']}/report-readiness"
    ).json()
    assert readiness["visit_count"] == 3
    assert readiness["minimum_visits"] == 3

    change_json = db.execute(
        text(
            "SELECT changes FROM operator_case_change_logs "
            "WHERE case_id = :case_id AND action = 'timeline_updated'"
        ),
        {"case_id": created["id"]},
    ).scalar_one()
    encoded = json.dumps(change_json, ensure_ascii=False)
    assert "timeline_sha256" in encoded
    assert "2026-01-01" not in encoded
    assert '"value"' not in encoded
    assert '"indicators"' not in encoded


@pytest.mark.parametrize(
    ("disease_id", "stage", "foreign_indicator", "unit"),
    [
        (1, "pre_cirrhosis", "MMSE", "分"),
        (2, "mci", "ALT", "U/L"),
    ],
)
def test_cross_disease_indicator_is_rejected_at_aggregate_boundary(
    client, disease_id, stage, foreign_indicator, unit
):
    payload = {
        "disease_id": disease_id,
        "age": 56,
        "sex": "male",
        "baseline_stage": stage,
        "visits": [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": foreign_indicator, "value": 20, "unit": unit}],
            }
        ],
    }
    response = client(1).post(
        "/api/v1/operator/longitudinal-cases",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "visits.0.indicators"


def _case_with_old_timestamp(operator, db):
    payload = _payload()
    second_visit = deepcopy(payload["visits"][0])
    second_visit["visit_date"] = "2026-02-01"
    payload["visits"].append(second_visit)
    response = operator.post(
        "/api/v1/operator/longitudinal-cases",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    created = response.json()
    before = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.execute(
        text("UPDATE operator_cases SET updated_at = :before WHERE id = :id"),
        {"before": before, "id": created["id"]},
    )
    db.commit()
    db.expire_all()
    editable = {key: created[key] for key in ("age", "sex", "baseline_stage", "notes")}
    editable["visits"] = deepcopy(_editable_visits(created["visits"]))
    return created, editable, before


@pytest.mark.parametrize("change", ["edit", "append", "remove"])
def test_visit_only_save_updates_case_timestamp_and_list_order(client, db, change):
    operator = client(1)
    created, payload, before = _case_with_old_timestamp(operator, db)
    other_response = operator.post(
        "/api/v1/operator/longitudinal-cases",
        json=_payload(),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert other_response.status_code == 201
    other_id = other_response.json()["id"]
    assert operator.get("/api/v1/operator/longitudinal-cases").json()["cases"][0]["id"] == other_id

    if change == "edit":
        payload["visits"][0]["indicators"][0]["value"] = 43
    elif change == "append":
        extra = deepcopy(payload["visits"][0])
        extra["visit_date"] = "2026-03-01"
        payload["visits"].append(extra)
    else:
        payload["visits"].pop()
    payload["change_reason"] = "修正访视"
    response = operator.put(
        f"/api/v1/operator/longitudinal-cases/{created['id']}", json=payload
    )
    assert response.status_code == 200
    saved = response.json()
    timestamp = db.execute(
        text("SELECT updated_at FROM operator_cases WHERE id = :id"), {"id": created["id"]}
    ).scalar_one()
    assert timestamp > before
    assert datetime.fromisoformat(saved["updated_at"]) == timestamp
    assert saved["created_at"] == created["created_at"]
    assert len(saved["visits"]) == len(payload["visits"])
    assert saved["visits"][0]["indicators"] == payload["visits"][0]["indicators"]
    assert operator.get("/api/v1/operator/longitudinal-cases").json()["cases"][0]["id"] == created["id"]


def test_unchanged_save_preserves_case_timestamp_and_audit(client, db):
    operator = client(1)
    created, payload, before = _case_with_old_timestamp(operator, db)
    response = operator.put(
        f"/api/v1/operator/longitudinal-cases/{created['id']}", json=payload
    )
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["updated_at"]) == before
    assert db.execute(text("SELECT updated_at FROM operator_cases")).scalar_one() == before
    assert db.execute(text("SELECT count(*) FROM operator_case_change_logs")).scalar_one() == 1


def test_failed_visit_save_rolls_back_case_timestamp_and_timeline(client, db, monkeypatch):
    operator = client(1)
    created, payload, before = _case_with_old_timestamp(operator, db)
    payload["visits"][0]["indicators"][0]["value"] = 43
    payload["change_reason"] = "修正访视"

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr("app.services.operator_case_commands.append_case_change_log", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        operator.put(f"/api/v1/operator/longitudinal-cases/{created['id']}", json=payload)
    assert db.execute(text("SELECT updated_at FROM operator_cases")).scalar_one() == before
    assert db.execute(text("SELECT count(*) FROM operator_case_change_logs")).scalar_one() == 1
    restored = operator.get(f"/api/v1/operator/longitudinal-cases/{created['id']}")
    assert restored.status_code == 200
    assert restored.json()["visits"] == created["visits"]
