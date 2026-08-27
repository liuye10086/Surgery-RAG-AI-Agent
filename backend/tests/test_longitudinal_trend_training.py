from __future__ import annotations

from datetime import date

import pytest

from app.services.longitudinal_dataset import PatientTimeline, TimelineVisit


def _visit(day: str, **indicators) -> TimelineVisit:
    return TimelineVisit(
        visit_date=date.fromisoformat(day),
        indicators=tuple(
            {"name": name, "value": value} for name, value in indicators.items()
        ),
        patient_age=65,
        sex="female",
        input_position=0,
    )


def _timeline(group: int, visits, disease="ad") -> PatientTimeline:
    from app.services.disease_progression import get_progression_adapter

    return PatientTimeline(
        adapter=get_progression_adapter(disease),
        source_dataset=f"{disease}_fixture",
        patient_label=f"PRIVATE-{group}",
        group_id=f"patient.v1.{group:064x}",
        is_synthetic=False,
        source_document="private.docx",
        import_version="1.0.0",
        final_stage="normal" if disease == "ad" else "fatty_liver",
        event_dates={},
        visits=tuple(visits),
    )


def _split(timelines, disease="ad"):
    from app.services.longitudinal_group_split import make_disease_group_split

    samples = [
        type(
            "SplitSample",
            (),
            {
                "identity": type(
                    "Identity",
                    (),
                    {"disease": disease, "group_id": timeline.group_id},
                )(),
                "label": type("Label", (), {"trend_label": "fixture"})(),
                "task": f"{disease}.trend.fixture",
            },
        )()
        for index, timeline in enumerate(timelines)
    ]
    return make_disease_group_split(
        samples,
        disease,
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )


@pytest.mark.parametrize(
    ("current", "following", "tolerance", "expected"),
    [
        (100.0, 104.9, 0.05, "stable"),
        (100.0, 105.1, 0.05, "rising"),
        (100.0, 94.9, 0.05, "falling"),
    ],
)
def test_direction_boundaries_are_versioned(current, following, tolerance, expected):
    from app.services.longitudinal_trend_training import direction_label

    assert direction_label(current, following, tolerance) == expected


def test_next_visit_value_is_label_only_and_never_a_feature():
    from app.services.longitudinal_trend_training import (
        TREND_CONTRACTS,
        build_trend_rows,
    )

    timelines = [
        _timeline(
            index,
            [
                _visit("2023-01-01", mmse=30 - index),
                _visit("2023-06-01", mmse=29 - index),
                _visit("2024-01-01", mmse=28 - index),
                _visit("2024-06-01", mmse=20 - index),
            ],
        )
        for index in range(1, 11)
    ]
    rows = build_trend_rows(
        timelines, TREND_CONTRACTS[("ad", "mmse")], _split(timelines)
    )
    row = rows[0]
    assert row.label == "falling"
    assert "next_value" not in row.features
    assert row.max_feature_date < row.label_visit_date


def test_trend_features_are_not_latest_value_only():
    from app.services.longitudinal_trend_training import (
        TrendTrainingRow,
        build_trend_feature_catalog,
    )

    row = TrendTrainingRow(
        disease="ad",
        indicator="mmse",
        group_id="patient.v1." + "1" * 64,
        partition="development_train",
        as_of=date(2024, 1, 1),
        max_feature_date=date(2024, 1, 1),
        label_visit_date=date(2024, 6, 1),
        label="falling",
        features={
            "visit_count": 3,
            "observation_span_days": 365,
            "days_since_previous_visit": 180,
            "mmse.first": 30.0,
            "mmse.last": 27.0,
            "mmse.time_slope_per_day": -0.01,
            "mmse.missing_ratio": 0.0,
        },
    )
    names = set(build_trend_feature_catalog([row]).feature_names)
    assert {
        "visit_count",
        "observation_span_days",
        "days_since_previous_visit",
        "mmse.first",
        "mmse.last",
        "mmse.time_slope_per_day",
        "mmse.missing_ratio",
    } <= names


def test_trend_rows_reuse_disease_split_for_every_indicator():
    from app.services.longitudinal_trend_training import (
        TREND_CONTRACTS,
        build_trend_rows,
    )

    timelines = [
        _timeline(
            index,
            [
                _visit("2023-01-01", mmse=20 + index, moca=18 + index),
                _visit("2023-06-01", mmse=21 + index, moca=19 + index),
                _visit("2024-01-01", mmse=22 + index, moca=20 + index),
                _visit("2024-06-01", mmse=23 + index, moca=21 + index),
            ],
        )
        for index in range(1, 16)
    ]
    split = _split(timelines)
    rows = []
    for indicator in ("mmse", "moca"):
        rows.extend(
            build_trend_rows(
                timelines, TREND_CONTRACTS[("ad", indicator)], split
            )
        )
    assert {
        row.partition
        for row in rows
        if row.group_id in split.locked_test_groups
    } == {"locked_test"}


def test_trend_training_refuses_missing_direction_class(tmp_path):
    from app.services.longitudinal_trend_training import (
        TREND_CONTRACTS,
        TrendTrainingError,
        TrendTrainingRow,
        train_trend_candidate,
    )

    rows = [
        TrendTrainingRow(
            disease="ad",
            indicator="mmse",
            group_id=f"patient.v1.{index:064x}",
            partition="development_train",
            as_of=date(2024, 1, 1),
            max_feature_date=date(2024, 1, 1),
            label_visit_date=date(2024, 6, 1),
            label="rising" if index % 2 else "falling",
            features={"visit_count": 3, "mmse.last": float(index)},
        )
        for index in range(1, 16)
    ]
    timelines = [
        _timeline(
            index,
            [_visit("2023-01-01", mmse=1), _visit("2023-06-01", mmse=2), _visit("2024-01-01", mmse=3), _visit("2024-06-01", mmse=4)],
        )
        for index in range(1, 16)
    ]
    with pytest.raises(TrendTrainingError, match="trend_class_support_insufficient"):
        train_trend_candidate(
            rows,
            TREND_CONTRACTS[("ad", "mmse")],
            _split(timelines),
            None,
            tmp_path,
            seed=42,
        )


def test_direction_only_output_contract_forbids_future_value():
    from app.schemas.longitudinal_model_suite import OutputContract

    output = OutputContract(
        kind="multiclass",
        classes=["rising", "stable", "falling"],
        ordered=False,
        score_semantics="model_score",
        projected_value_supported=False,
        prediction_interval_supported=False,
    )
    assert output.projected_value_supported is False
    assert output.prediction_interval_supported is False


def _candidate_fixture(tmp_path):
    from app.schemas.longitudinal_model_training import DatasetInput
    from app.services.longitudinal_group_split import make_disease_group_split
    from app.services.longitudinal_trend_training import (
        TREND_CONTRACTS,
        TrendTrainingRow,
    )

    contract = TREND_CONTRACTS[("ad", "mmse")]
    labels = list(contract.class_order)
    rows = [
        TrendTrainingRow(
            disease="ad",
            indicator="mmse",
            group_id=f"patient.v1.{index:064x}",
            partition="development_train",
            as_of=date(2024, 1, 1),
            max_feature_date=date(2024, 1, 1),
            label_visit_date=date(2024, 6, 1),
            label=labels[index % 3],
            features={
                "visit_count": 3 + index % 3,
                "observation_span_days": 365,
                "days_since_previous_visit": 180,
                "mmse.first": float(20 + index % 5),
                "mmse.last": float(20 + index + (index % 3) * 5),
                "mmse.time_slope_per_day": float(index % 3 - 1) / 100,
                "mmse.missing_ratio": 0.0,
            },
        )
        for index in range(1, 46)
    ]
    samples = [
        type(
            "SplitSample",
            (),
            {
                "identity": type(
                    "Identity",
                    (),
                    {"disease": "ad", "group_id": row.group_id},
                )(),
                "label": type("Label", (), {"trend_label": row.label})(),
                "task": "ad.trend.mmse",
            },
        )()
        for row in rows
    ]
    split = make_disease_group_split(
        samples,
        "ad",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    assignments = split.assignments()
    rows = [
        TrendTrainingRow(
            **{**row.__dict__, "partition": assignments[row.group_id]}
        )
        for row in rows
    ]
    dataset = DatasetInput(
        dataset_dir=str(tmp_path / "dataset"),
        schema_version="longitudinal_fixed_window_dataset.v1",
        manifest_sha256="a" * 64,
        data_content_sha256="b" * 64,
        file_sha256_by_path={
            "ad/real_train.jsonl": "c" * 64,
            "group_splits.json": "d" * 64,
        },
        group_split_file="group_splits.json",
        group_split_sha256="d" * 64,
    )
    return rows, contract, split, dataset


def test_trend_candidate_writes_direction_only_v2_bundle(tmp_path):
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2, EvaluationArtifact
    from app.services.longitudinal_trend_training import (
        train_trend_candidate,
        write_trend_candidate_bundle,
    )

    rows, contract, split, dataset = _candidate_fixture(tmp_path)
    candidate = train_trend_candidate(
        rows, contract, split, dataset, tmp_path / "fit", seed=42
    )
    bundle = write_trend_candidate_bundle(candidate, tmp_path / "bundles")
    metadata = ArtifactMetadataV2.model_validate_json(
        bundle.metadata_path.read_text(encoding="utf-8")
    )
    evaluation = EvaluationArtifact.model_validate_json(
        bundle.evaluation_path.read_text(encoding="utf-8")
    )

    assert metadata.artifact_type == "trend"
    assert metadata.task == "ad.next_visit_trend.mmse"
    assert metadata.output_contract.classes == ["rising", "stable", "falling"]
    assert metadata.output_contract.projected_value_supported is False
    assert metadata.output_contract.prediction_interval_supported is False
    assert metadata.split_sha256 == split.sha256
    assert evaluation.locked_test_used_for_selection is False
    assert len(list(bundle.bundle_dir.iterdir())) == 3


def test_trend_locked_test_runs_only_after_candidate_freeze(monkeypatch, tmp_path):
    import app.services.longitudinal_trend_training as training

    rows, contract, split, dataset = _candidate_fixture(tmp_path)
    calls = []
    original = training.evaluate_trend_locked_test

    def record(*args, **kwargs):
        calls.append("locked")
        return original(*args, **kwargs)

    monkeypatch.setattr(training, "evaluate_trend_locked_test", record)
    candidate = training.train_trend_candidate(
        rows, contract, split, dataset, tmp_path / "fit", seed=42
    )

    assert candidate.selection_trace[-1] == "candidate_frozen"
    assert calls == ["locked"]
