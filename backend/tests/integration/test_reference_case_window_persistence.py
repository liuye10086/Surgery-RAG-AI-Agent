"""Real PostgreSQL persistence contract for reference windows."""

from app.db.models import CaseRecord, ReferenceCaseWindow
from app.services.reference_case_windows import synchronize_reference_case_windows


def _seed_active_release(db):
    visits = [
        ("2024-01-01", 20.0),
        ("2024-04-01", 22.0),
        ("2024-07-01", 24.0),
        ("2024-10-01", 26.0),
    ]
    for index, (visit_date, value) in enumerate(visits, start=1):
        db.add(CaseRecord(
            disease_id=1,
            patient_label="source-patient-001",
            anonymous_case_code="CASE-ABCD-2345",
            indicators=[{"name": "alt", "value": value, "unit": "U/L"}],
            confirmed=True,
            case_metadata={
                "logical_dataset": "longitudinal_300",
                "source_dataset": "longitudinal_300",
                "dataset_release_id": "fl-integration-v1",
                "dataset_active": True,
                "data_content_sha256": "a" * 64,
                "visit_date": visit_date,
                "visit_index": index,
                "patient_age": 62,
                "sex": "female",
                "final_stage": "cirrhosis",
                "event_dates": {"cirrhosis_date": "2024-12-15"},
                "source_document": "source-001.docx",
                "is_synthetic": False,
            },
        ))
    db.commit()


def test_reference_window_apply_is_complete_private_and_idempotent(db):
    _seed_active_release(db)

    first = synchronize_reference_case_windows(db, "fatty_liver", apply=True)
    second = synchronize_reference_case_windows(db, "fatty_liver", apply=True)

    assert first.logical_dataset == "longitudinal_300"
    assert first.total_windows == first.eligible_windows == first.inserted == 2
    assert second.inserted == 0
    assert second.unchanged == 2
    rows = db.query(ReferenceCaseWindow).order_by(ReferenceCaseWindow.as_of).all()
    assert len(rows) == 2
    assert all(row.eligibility_status == "eligible" for row in rows)
    assert all(row.outcome_status == "positive" for row in rows)
    assert all(row.outcome_value["event_date"] == "2024-12-15" for row in rows)
    assert all("source-patient-001" not in str(row.source_trace) for row in rows)
