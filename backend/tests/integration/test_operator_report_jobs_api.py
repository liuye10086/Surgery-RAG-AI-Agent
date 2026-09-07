def test_owner_can_recover_and_cancel_while_other_account_cannot_read(
    client, queued_report
):
    owner, other = client(1), client(2)
    prefix = f"/api/v1/operator/reports/{queued_report}"
    assert other.get(prefix + "/generation-status").status_code == 404
    assert other.post(prefix + "/cancel").status_code == 404
    assert other.get(prefix + "/events").status_code == 404
    assert owner.get(prefix + "/generation-status").json()["status"] == "queued"
    response = owner.post(prefix + "/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    revision = response.json()["revision"]
    assert owner.post(prefix + "/cancel").json()["revision"] == revision
    events = owner.get(prefix + "/events")
    assert events.status_code == 200
    assert '"status":"cancelled"' in events.text
    assert '"status":"completed"' not in events.text


def test_old_writer_cannot_bypass_disabled_admission(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REPORT_JOBS_ENABLED", False)
    response = client(1).post("/api/v1/operator/longitudinal-cases/1/reports", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "report_jobs_unavailable"


def test_active_report_delete_requires_explicit_cancel(client, queued_report):
    owner = client(1)
    assert owner.delete(f"/api/v1/operator/reports/{queued_report}").status_code == 409
    assert (
        owner.post(f"/api/v1/operator/reports/{queued_report}/cancel").status_code
        == 200
    )
    assert owner.delete(f"/api/v1/operator/reports/{queued_report}").status_code == 204
