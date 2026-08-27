from __future__ import annotations

import pytest


def _sqlite_db():
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker

    from app.db.models import CaseRecord, Disease

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    engine = create_engine("sqlite:///:memory:")
    Disease.__table__.create(engine)
    CaseRecord.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_release(db, release_id: str, *, active: bool):
    from app.db.models import CaseRecord, Disease

    disease = db.query(Disease).filter(Disease.name == "脂肪肝").first()
    if disease is None:
        disease = Disease(name="脂肪肝")
        db.add(disease)
        db.flush()
    db.add(
        CaseRecord(
            disease_id=disease.id,
            patient_label=f"case-{release_id}",
            indicators=[],
            confirmed=True,
            case_metadata={
                "source_dataset": "longitudinal_300",
                "logical_dataset": "longitudinal_300",
                "dataset_release_id": release_id,
                "dataset_active": active,
                "visit_date": "2024-01-01",
            },
        )
    )
    db.commit()


def _active_release_ids(db) -> set[str]:
    from app.db.models import CaseRecord

    return {
        row.case_metadata["dataset_release_id"]
        for row in db.query(CaseRecord).all()
        if row.case_metadata.get("dataset_active") is True
    }


def test_activate_data_release_keeps_exactly_one_active_version():
    from app.services.longitudinal_data_release import activate_data_release

    db = _sqlite_db()
    _seed_release(db, "fl-v1", active=True)
    _seed_release(db, "fl-v2", active=False)

    result = activate_data_release(db, "longitudinal_300", "fl-v2")
    db.commit()

    assert result.previous_release_id == "fl-v1"
    assert result.active_release_id == "fl-v2"
    assert _active_release_ids(db) == {"fl-v2"}


def test_failed_activation_rolls_back_to_previous_release(monkeypatch):
    from app.services.longitudinal_data_release import activate_data_release

    db = _sqlite_db()
    _seed_release(db, "fl-v1", active=True)
    _seed_release(db, "fl-v2", active=False)
    original_flush = db.flush

    def fail_flush(*args, **kwargs):
        original_flush(*args, **kwargs)
        raise RuntimeError("activation failed")

    monkeypatch.setattr(db, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="activation failed"):
        activate_data_release(db, "longitudinal_300", "fl-v2")
    db.rollback()
    monkeypatch.setattr(db, "flush", original_flush)

    assert _active_release_ids(db) == {"fl-v1"}


def test_select_active_release_rows_prefers_explicit_active_over_legacy():
    from types import SimpleNamespace

    from app.services.longitudinal_data_release import select_active_release_rows

    legacy = SimpleNamespace(
        case_metadata={"source_dataset": "longitudinal_300"}
    )
    inactive = SimpleNamespace(
        case_metadata={
            "logical_dataset": "longitudinal_300",
            "dataset_release_id": "fl-v1",
            "dataset_active": False,
        }
    )
    active = SimpleNamespace(
        case_metadata={
            "logical_dataset": "longitudinal_300",
            "dataset_release_id": "fl-v2",
            "dataset_active": True,
        }
    )

    assert select_active_release_rows(
        [legacy, inactive, active], "longitudinal_300"
    ) == [active]


def test_select_active_release_rows_uses_legacy_only_without_explicit_release():
    from types import SimpleNamespace

    from app.services.longitudinal_data_release import select_active_release_rows

    legacy = SimpleNamespace(
        case_metadata={"source_dataset": "longitudinal_300"}
    )
    other = SimpleNamespace(
        case_metadata={"source_dataset": "ad_longitudinal_300"}
    )

    assert select_active_release_rows(
        [legacy, other], "longitudinal_300"
    ) == [legacy]
