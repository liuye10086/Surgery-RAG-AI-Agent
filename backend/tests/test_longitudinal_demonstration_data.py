from __future__ import annotations

from datetime import datetime, timezone


def _partition_labels(rows, split):
    assignments = split.assignments()
    result = {
        "development_train": set(),
        "development_validation": set(),
        "locked_test": set(),
    }
    for row in rows:
        result[assignments[row.group_id]].add(row.label)
    return result


def test_demonstration_rows_are_reproducible_and_explicitly_synthetic():
    from app.services.longitudinal_demonstration_data import (
        build_demonstration_case_rows,
    )

    first = build_demonstration_case_rows(patients_per_disease=15, seed=20260827)
    second = build_demonstration_case_rows(patients_per_disease=15, seed=20260827)

    assert first == second
    assert len(first) == 15 * 2 * 10
    assert all(row["metadata"]["is_synthetic"] is True for row in first)
    assert all(
        row["metadata"]["synthetic_purpose"] == "demonstration_training_only"
        for row in first
    )
    assert all("source_document" not in row["metadata"] for row in first)


def test_demonstration_release_covers_all_stage_and_trend_classes_in_every_partition(
    tmp_path,
):
    from app.services.longitudinal_dataset import build_fixed_window_dataset
    from app.services.longitudinal_dataset_export import export_fixed_window_dataset
    from app.services.longitudinal_demonstration_data import (
        build_demonstration_case_rows,
    )
    from app.services.longitudinal_group_split import read_disease_group_splits
    from app.services.longitudinal_stage_training import build_stage_rows
    from app.services.longitudinal_trend_training import (
        TREND_CONTRACTS,
        build_trend_rows,
    )

    result = build_fixed_window_dataset(
        build_demonstration_case_rows(patients_per_disease=15, seed=20260827)
    )
    target = tmp_path / "dataset"
    export_fixed_window_dataset(
        result,
        target,
        generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        code_version="test-revision",
        training_profile="synthetic_demonstration",
        generator_version="longitudinal-demonstration.v1",
        generator_seed=20260827,
    )
    splits = read_disease_group_splits(target)

    expected_stage = {
        "fatty_liver": {
            "stay_pre_cirrhosis",
            "cirrhosis",
            "stay_cirrhosis",
            "hcc",
        },
        "ad": {"stay_normal", "mci", "stay_mci", "dementia"},
    }
    for disease in ("fatty_liver", "ad"):
        timelines = [
            timeline
            for timeline in result.synthetic_timelines
            if timeline.adapter.dataset == disease
        ]
        stage_rows = build_stage_rows(
            timelines,
            disease,
            splits[disease],
            allow_synthetic=True,
        )
        for labels in _partition_labels(stage_rows, splits[disease]).values():
            assert labels == expected_stage[disease]

        for (contract_disease, _), contract in TREND_CONTRACTS.items():
            if contract_disease != disease:
                continue
            trend_rows = build_trend_rows(
                timelines,
                contract,
                splits[disease],
                allow_synthetic=True,
            )
            for partition in (
                "development_train",
                "development_validation",
                "locked_test",
            ):
                assert {
                    row.label for row in trend_rows if row.partition == partition
                } == set(contract.class_order)


def test_ad_demonstration_stage_does_not_train_post_dementia_preservation():
    from app.services.longitudinal_dataset import build_fixed_window_dataset
    from app.services.longitudinal_demonstration_data import (
        build_demonstration_case_rows,
    )
    from app.services.longitudinal_group_split import make_disease_group_split
    from app.services.longitudinal_stage_training import build_stage_rows

    result = build_fixed_window_dataset(
        build_demonstration_case_rows(patients_per_disease=15, seed=20260827)
    )
    samples = [
        sample
        for sample in result.synthetic_audit
        if sample.identity.disease == "ad"
        and sample.label.status in {"positive", "negative"}
    ]
    split = make_disease_group_split(
        samples,
        "ad",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    rows = build_stage_rows(
        [
            timeline
            for timeline in result.synthetic_timelines
            if timeline.adapter.dataset == "ad"
        ],
        "ad",
        split,
        allow_synthetic=True,
    )

    assert "stay_dementia" not in {row.label for row in rows}
