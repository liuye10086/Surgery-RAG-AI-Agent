"""Patient timeline validation for the P0-03 dataset builder."""

from copy import deepcopy

import pytest

from app.services.longitudinal_dataset import (
    DatasetValidationError,
    rebuild_patient_timelines,
    stable_group_id,
)


def patient_rows(
    *,
    source_dataset: str = "longitudinal_300",
    patient_label: str = "P001",
    disease_code: str = "fatty_liver",
    disease_name: str = "脂肪肝",
) -> list[dict]:
    dates = ["2023-01-01", "2023-06-01", "2024-01-01"]
    rows = []
    for index, visit_date in enumerate(dates, start=1):
        rows.append(
            {
                "record_id": index,
                "disease_code": disease_code,
                "disease_name": disease_name,
                "patient_label": patient_label,
                "indicators": [{"name": "ALT", "value": 10 + index}],
                "metadata": {
                    "visit_date": visit_date,
                    "patient_age": 60,
                    "sex": "female",
                    "final_stage": "fatty_liver",
                    "event_dates": {},
                    "source_dataset": source_dataset,
                    "is_synthetic": False,
                    "import_version": "1.0.0",
                },
            }
        )
    return rows


def test_group_id_is_stable_and_source_scoped():
    first = stable_group_id("longitudinal_300", "P001")

    assert first == stable_group_id("longitudinal_300", "P001")
    assert first == stable_group_id(" longitudinal_300 ", " P001 ")
    assert first != stable_group_id("another_dataset", "P001")
    assert first.startswith("patient.v1.")
    assert len(first.removeprefix("patient.v1.")) == 64


@pytest.mark.parametrize("field", ["source_dataset", "visit_date", "is_synthetic"])
def test_missing_required_metadata_fails_whole_build(field):
    rows = patient_rows()
    rows[0]["metadata"].pop(field)

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code == f"missing_{field}"
    assert "P001" not in str(caught.value)


def test_missing_patient_label_fails_without_exposing_identity():
    rows = patient_rows()
    rows[0]["patient_label"] = "  "

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code == "missing_patient_label"
    assert str(caught.value) == "missing_patient_label"


def test_missing_medical_indicator_does_not_reject_patient():
    rows = patient_rows()
    rows[1]["indicators"] = []

    patients, _ = rebuild_patient_timelines(rows)

    assert len(patients) == 1
    assert patients[0].visits[1].indicators == ()


def test_duplicate_same_day_visit_fails_instead_of_merging():
    rows = patient_rows()
    rows[2]["metadata"]["visit_date"] = rows[1]["metadata"]["visit_date"]

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code == "duplicate_patient_visit_date"


def test_valid_out_of_order_rows_are_sorted_and_audited():
    rows = list(reversed(patient_rows()))

    patients, audit = rebuild_patient_timelines(rows)

    assert [visit.visit_date.isoformat() for visit in patients[0].visits] == [
        "2023-01-01",
        "2023-06-01",
        "2024-01-01",
    ]
    assert audit.reordered_patient_count == 1


@pytest.mark.parametrize("bad_date", [None, "", "not-a-date", "2024-02-30"])
def test_invalid_visit_date_fails(bad_date):
    rows = patient_rows()
    rows[0]["metadata"]["visit_date"] = bad_date

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code in {"missing_visit_date", "invalid_visit_date"}


@pytest.mark.parametrize("bad_provenance", [0, 1, "false", None])
def test_provenance_must_be_a_real_boolean(bad_provenance):
    rows = patient_rows()
    rows[0]["metadata"]["is_synthetic"] = bad_provenance

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code in {"missing_is_synthetic", "invalid_is_synthetic"}


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("event_dates", {"cirrhosis_date": "2025-01-01"}, "conflicting_event_dates"),
        ("final_stage", "cirrhosis", "conflicting_final_stage"),
        ("patient_age", 61, "conflicting_patient_age"),
        ("sex", "male", "conflicting_sex"),
        ("import_version", "2.0.0", "conflicting_import_version"),
    ],
)
def test_patient_metadata_conflicts_fail(field, value, code):
    rows = patient_rows()
    rows[1]["metadata"][field] = value

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code == code


def test_unexpected_or_invalid_event_date_fails():
    rows = patient_rows()
    rows[0]["metadata"]["event_dates"] = {"dementia_date": "2025-01-01"}
    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)
    assert caught.value.code == "unexpected_event_field"

    rows = patient_rows()
    rows[0]["metadata"]["event_dates"] = {"cirrhosis_date": "bad"}
    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)
    assert caught.value.code == "invalid_event_date"


def test_different_disease_under_same_source_patient_identity_fails():
    rows = patient_rows()
    conflicting = deepcopy(rows[0])
    conflicting["record_id"] = 99
    conflicting["disease_code"] = "ad"
    conflicting["disease_name"] = "阿尔茨海默病"
    conflicting["metadata"]["visit_date"] = "2024-06-01"
    conflicting["metadata"]["final_stage"] = "0"
    rows.append(conflicting)

    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)

    assert caught.value.code == "conflicting_disease"


def test_same_patient_label_from_different_sources_remains_separate():
    rows = patient_rows()
    rows += patient_rows(source_dataset="another_dataset")

    patients, _ = rebuild_patient_timelines(rows)

    assert len(patients) == 2
    assert patients[0].group_id != patients[1].group_id


def test_missing_then_known_demographics_are_not_backfilled():
    rows = patient_rows()
    rows[0]["metadata"]["patient_age"] = None
    rows[0]["metadata"]["sex"] = None

    patients, _ = rebuild_patient_timelines(rows)

    assert patients[0].visits[0].patient_age is None
    assert patients[0].visits[0].sex is None
    assert patients[0].visits[1].patient_age == 60
    assert patients[0].visits[1].sex == "female"


def test_invalid_optional_demographics_become_missing():
    rows = patient_rows()
    rows[0]["metadata"]["patient_age"] = "unknown"
    rows[0]["metadata"]["sex"] = "unknown"

    patients, _ = rebuild_patient_timelines(rows)

    assert patients[0].visits[0].patient_age is None
    assert patients[0].visits[0].sex is None
