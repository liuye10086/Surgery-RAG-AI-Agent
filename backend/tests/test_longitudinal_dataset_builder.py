"""End-to-end in-memory assembly for the fixed-window dataset."""

from copy import deepcopy

import pytest

from app.services.longitudinal_dataset import (
    DatasetValidationError,
    assert_feature_namespace_safe,
    build_fixed_window_dataset,
)


def patient_rows(
    patient_label: str,
    *,
    source_dataset: str = "longitudinal_300",
    disease_name: str = "脂肪肝",
    visit_dates: tuple[str, ...] = ("2023-01-01", "2023-06-01", "2024-01-01"),
    event_dates: dict | None = None,
    final_stage="fatty_liver",
    is_synthetic: bool = False,
    indicator_name: str = "ALT",
) -> list[dict]:
    rows = []
    for index, visit_date in enumerate(visit_dates, start=1):
        rows.append(
            {
                "record_id": index,
                "disease_name": disease_name,
                "patient_label": patient_label,
                "confirmed": final_stage not in {"fatty_liver", "0"},
                "indicators": [{"name": indicator_name, "value": 10 + index}],
                "metadata": {
                    "visit_date": visit_date,
                    "visit_index": index,
                    "total_visits": len(visit_dates),
                    "patient_age": 60,
                    "sex": "female",
                    "cohort_group": "internal-only",
                    "final_stage": final_stage,
                    "event_dates": event_dates or {},
                    "source_dataset": source_dataset,
                    "is_synthetic": is_synthetic,
                    "import_version": "1.0.0",
                },
            }
        )
    return rows


def test_six_visits_generate_four_prefixes_using_all_history_to_as_of():
    rows = patient_rows(
        "P001",
        visit_dates=(
            "2022-07-01",
            "2023-01-01",
            "2023-07-01",
            "2024-01-01",
            "2024-07-01",
            "2025-01-01",
        ),
    )

    result = build_fixed_window_dataset(rows)

    assert [row.identity.history_visit_count for row in result.real_audit] == [
        3,
        4,
        5,
        6,
    ]
    assert [row.identity.as_of.isoformat() for row in result.real_audit] == [
        "2023-07-01",
        "2024-01-01",
        "2024-07-01",
        "2025-01-01",
    ]


def test_fewer_than_three_visits_produces_no_candidate_but_remains_in_summary():
    result = build_fixed_window_dataset(
        patient_rows("P001", visit_dates=("2023-01-01", "2024-01-01"))
    )

    assert result.real_audit == ()
    counts = result.summary.diseases["fatty_liver"].real
    assert counts.patient_count == 1
    assert counts.visit_count == 2
    assert counts.candidate_count == 0


def test_future_visit_values_cannot_change_existing_prefix_features():
    base_rows = patient_rows("P001")
    extended_rows = patient_rows(
        "P001",
        visit_dates=("2023-01-01", "2023-06-01", "2024-01-01", "2025-01-01"),
    )
    extended_rows[-1]["indicators"] = [
        {"name": "ALT", "value": 999},
        {"name": "CDR", "value": 3},
    ]

    base = build_fixed_window_dataset(base_rows).real_audit[0]
    extended = build_fixed_window_dataset(extended_rows).real_audit[0]

    assert base.identity.as_of == extended.identity.as_of
    assert base.features.model_dump(mode="json") == extended.features.model_dump(
        mode="json"
    )
    assert not any(
        key in extended.features.model_dump(mode="json")
        for key in ("confirmed", "total_visits", "visit_index", "cohort_group")
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "final_stage",
        "confirmed",
        "event_dates",
        "cirrhosis_date",
        "hcc_date",
        "dementia_date",
        "fatty_liver_date",
        "last_followup_date",
        "lost_to_followup",
        "total_visits",
        "visit_index",
        "cohort_group",
        "outcome_source",
        "assigned_final_stage",
        "inferred_stage",
        "source_dataset",
        "patient_label",
        "group_id",
        "is_synthetic",
    ],
)
def test_forbidden_feature_key_aborts_build(forbidden):
    with pytest.raises(DatasetValidationError) as caught:
        assert_feature_namespace_safe({"nested": {forbidden.upper(): "leak"}})

    assert caught.value.code == "forbidden_feature_field"


def test_forbidden_indicator_name_aborts_build():
    rows = patient_rows("P001", indicator_name="dementia_date")

    with pytest.raises(DatasetValidationError) as caught:
        build_fixed_window_dataset(rows)

    assert caught.value.code == "forbidden_feature_field"


def test_real_training_filters_non_trainable_and_synthetic_rows_but_keeps_audit():
    rows = []
    rows += patient_rows(
        "positive",
        event_dates={"cirrhosis_date": "2024-06-01"},
        final_stage="cirrhosis",
    )
    rows += patient_rows(
        "negative",
        event_dates={"cirrhosis_date": "2025-01-01"},
        final_stage="cirrhosis",
    )
    rows += patient_rows("insufficient", final_stage="fatty_liver")
    rows += patient_rows(
        "not-applicable",
        event_dates={"hcc_date": "2023-12-01"},
        final_stage="hcc",
    )
    rows += patient_rows(
        "synthetic-positive",
        event_dates={"cirrhosis_date": "2024-06-01"},
        final_stage="cirrhosis",
        is_synthetic=True,
    )

    result = build_fixed_window_dataset(rows)

    assert [sample.label.status for sample in result.real_train] == [
        "negative",
        "positive",
    ]
    assert {sample.label.status for sample in result.real_audit} == {
        "positive",
        "negative",
        "insufficient_observation",
        "not_applicable",
    }
    assert len(result.synthetic_audit) == 1
    assert result.synthetic_audit[0].label.status == "positive"
    assert all(not sample.identity.is_synthetic for sample in result.real_train)

    real = result.summary.diseases["fatty_liver"].real
    synthetic = result.summary.diseases["fatty_liver"].synthetic
    assert (real.positive_count, real.negative_count) == (1, 1)
    assert real.insufficient_observation_count == 1
    assert real.not_applicable_count == 1
    assert real.trainable_count == 2
    assert real.candidate_count == 4
    assert real.trainable_patient_count == 2
    assert synthetic.positive_count == 1


def test_prefixes_share_group_while_equal_labels_from_other_sources_do_not_merge():
    rows = patient_rows(
        "P001",
        visit_dates=("2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"),
    )
    rows += patient_rows(
        "P001",
        source_dataset="another_dataset",
        visit_dates=("2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"),
    )

    result = build_fixed_window_dataset(rows)
    groups_by_source = {}
    for sample in result.real_audit:
        groups_by_source.setdefault(sample.identity.source_dataset, set()).add(
            sample.identity.group_id
        )

    assert all(len(groups) == 1 for groups in groups_by_source.values())
    assert groups_by_source["longitudinal_300"] != groups_by_source["another_dataset"]
    assert result.summary.diseases["fatty_liver"].real.patient_count == 2


def test_input_row_order_does_not_change_output_order():
    rows = patient_rows("P002") + patient_rows("P001")

    forward = build_fixed_window_dataset(rows)
    reverse = build_fixed_window_dataset(list(reversed(deepcopy(rows))))

    forward_keys = [
        (sample.identity.source_dataset, sample.identity.patient_label, sample.identity.as_of)
        for sample in forward.real_audit
    ]
    reverse_keys = [
        (sample.identity.source_dataset, sample.identity.patient_label, sample.identity.as_of)
        for sample in reverse.real_audit
    ]
    assert forward_keys == reverse_keys


def test_summary_always_contains_both_diseases():
    result = build_fixed_window_dataset(patient_rows("P001"))

    assert set(result.summary.diseases) == {"fatty_liver", "ad"}
    assert result.summary.diseases["ad"].real.patient_count == 0
