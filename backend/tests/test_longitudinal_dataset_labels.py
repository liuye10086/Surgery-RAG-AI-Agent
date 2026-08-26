"""Disease and time-window labels for the P0-03 dataset."""

from datetime import date

import pytest

from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_dataset import (
    PatientTimeline,
    TimelineVisit,
    label_fixed_window,
    resolve_target,
    stable_group_id,
)


def _visits(*days: str, extra_indicators: dict[str, list[dict]] | None = None):
    extra_indicators = extra_indicators or {}
    return tuple(
        TimelineVisit(
            visit_date=date.fromisoformat(day),
            indicators=tuple(extra_indicators.get(day, [])),
            patient_age=60,
            sex="female",
            input_position=index,
        )
        for index, day in enumerate(days)
    )


def _patient(
    *,
    adapter,
    event_dates: dict[str, str | None],
    final_stage,
    visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2025-02-01"),
    extra_indicators: dict[str, list[dict]] | None = None,
) -> PatientTimeline:
    normalized_events = {
        key: date.fromisoformat(value)
        for key, value in event_dates.items()
        if value is not None
    }
    source = "ad_longitudinal_300" if adapter.dataset == "ad" else "longitudinal_300"
    return PatientTimeline(
        adapter=adapter,
        source_dataset=source,
        patient_label="P001",
        group_id=stable_group_id(source, "P001"),
        is_synthetic=False,
        source_document=None,
        import_version="1.0.0",
        final_stage=final_stage,
        event_dates=normalized_events,
        visits=_visits(*visit_days, extra_indicators=extra_indicators),
    )


def fatty_patient(
    *,
    cirrhosis_date: str | None,
    hcc_date: str | None,
    final_stage="hcc",
    visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2025-02-01"),
) -> PatientTimeline:
    return _patient(
        adapter=FATTY_LIVER_ADAPTER,
        event_dates={"cirrhosis_date": cirrhosis_date, "hcc_date": hcc_date},
        final_stage=final_stage,
        visit_days=visit_days,
    )


def ad_patient(
    *,
    dementia_date: str | None,
    final_stage="1",
    visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2025-02-01"),
    extra_indicators: dict[str, list[dict]] | None = None,
) -> PatientTimeline:
    return _patient(
        adapter=AD_ADAPTER,
        event_dates={"dementia_date": dementia_date},
        final_stage=final_stage,
        visit_days=visit_days,
        extra_indicators=extra_indicators,
    )


@pytest.mark.parametrize(
    ("event_day", "expected_status"),
    [
        ("2024-01-01", "not_applicable"),
        ("2024-01-02", "positive"),
        ("2024-12-31", "positive"),
        ("2025-01-01", "negative"),
    ],
)
def test_ad_event_boundary(event_day, expected_status):
    patient = ad_patient(dementia_date=event_day)

    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert decision.status == expected_status


def test_fatty_liver_pre_cirrhosis_accepts_cirrhosis_or_direct_hcc():
    cirrhosis = fatty_patient(cirrhosis_date="2024-06-01", hcc_date=None)
    direct_hcc = fatty_patient(cirrhosis_date=None, hcc_date="2024-06-01")

    for patient in (cirrhosis, direct_hcc):
        decision = label_fixed_window(patient, date(2024, 1, 1))
        assert decision.status == "positive"
        assert decision.target_event == "cirrhosis_or_hcc"


def test_fatty_liver_after_cirrhosis_targets_hcc_only():
    patient = fatty_patient(
        cirrhosis_date="2023-12-01",
        hcc_date="2024-08-01",
    )

    target = resolve_target(patient, date(2024, 1, 1))
    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert target.current_state == "cirrhosis"
    assert target.target_event == "hcc"
    assert decision.status == "positive"
    assert decision.event_type == "hcc_date"


def test_fatty_liver_after_hcc_is_not_applicable():
    patient = fatty_patient(
        cirrhosis_date="2023-01-01",
        hcc_date="2023-12-01",
    )

    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert decision.status == "not_applicable"
    assert decision.reason_code == "target_already_reached"
    assert decision.target_event == "none"


def test_full_window_without_event_is_negative():
    patient = ad_patient(dementia_date=None, final_stage="0")

    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert decision.status == "negative"
    assert decision.reason_code == "full_window_observed_without_event"


def test_short_followup_without_event_is_insufficient():
    patient = ad_patient(
        dementia_date=None,
        final_stage="0",
        visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2024-06-01"),
    )

    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert decision.status == "insufficient_observation"
    assert decision.reason_code == "followup_ends_before_window"


def test_explicit_event_after_window_is_negative_evidence():
    patient = ad_patient(
        dementia_date="2025-01-01",
        final_stage="1",
        visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2024-06-01"),
    )

    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert decision.status == "negative"
    assert decision.reason_code == "target_event_after_window"
    assert decision.event_date == date(2025, 1, 1)


@pytest.mark.parametrize(
    "patient",
    [
        fatty_patient(
            cirrhosis_date=None,
            hcc_date=None,
            final_stage="cirrhosis",
        ),
        fatty_patient(
            cirrhosis_date="2023-12-01",
            hcc_date=None,
            final_stage="hcc",
        ),
        ad_patient(dementia_date=None, final_stage="1"),
        ad_patient(dementia_date=None, final_stage="2"),
    ],
)
def test_final_progression_without_target_date_is_insufficient(patient):
    decision = label_fixed_window(patient, date(2024, 1, 1))

    assert decision.status == "insufficient_observation"
    assert decision.reason_code == "progressed_without_target_date"


def test_ad_before_dementia_uses_task_state_not_fabricated_mci_date():
    patient = ad_patient(dementia_date="2024-08-01", final_stage="1")

    target = resolve_target(patient, date(2024, 1, 1))

    assert target.current_state == "pre_dementia"
    assert target.target_event == "dementia"


def test_future_cognitive_scores_do_not_replace_dementia_event():
    base = ad_patient(
        dementia_date=None,
        final_stage="0",
        visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2024-06-01"),
    )
    changed = ad_patient(
        dementia_date=None,
        final_stage="0",
        visit_days=("2023-01-01", "2023-06-01", "2024-01-01", "2024-06-01"),
        extra_indicators={
            "2024-06-01": [
                {"name": "CDR", "value": 3},
                {"name": "MMSE", "value": 5},
                {"name": "MoCA", "value": 3},
            ]
        },
    )

    assert label_fixed_window(base, date(2024, 1, 1)) == label_fixed_window(
        changed, date(2024, 1, 1)
    )
