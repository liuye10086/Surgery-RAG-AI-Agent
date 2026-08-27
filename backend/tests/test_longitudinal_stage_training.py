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
        patient_age=60,
        sex="female",
        input_position=0,
    )


def _timeline(
    group: str,
    visits: list[TimelineVisit],
    *,
    disease: str = "fatty_liver",
    event_dates: dict[str, date] | None = None,
    final_stage: str = "fatty_liver",
) -> PatientTimeline:
    from app.services.disease_progression import get_progression_adapter

    return PatientTimeline(
        adapter=get_progression_adapter(disease),
        source_dataset=f"{disease}_fixture",
        patient_label=f"PRIVATE-{group}",
        group_id=f"patient.v1.{int(group):064x}",
        is_synthetic=False,
        source_document="private.docx",
        import_version="1.0.0",
        final_stage=final_stage,
        event_dates=event_dates or {},
        visits=tuple(visits),
    )


def _split(timelines, disease="fatty_liver"):
    from app.services.longitudinal_group_split import make_disease_group_split

    samples = []
    for index, timeline in enumerate(timelines):
        samples.append(
            type(
                "SplitSample",
                (),
                {
                    "identity": type(
                        "Identity",
                        (),
                        {"disease": disease, "group_id": timeline.group_id},
                    )(),
                    "label": type(
                        "Label", (), {"training_label": index % 2}
                    )(),
                    "task": f"{disease}.stage",
                },
            )()
        )
    return make_disease_group_split(
        samples,
        disease,
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )


def test_stage_label_uses_only_next_365_days_and_can_preserve_current_stage():
    from app.services.longitudinal_stage_training import build_stage_rows

    timelines = [
        _timeline(
            "1",
            [
                _visit("2023-01-01", alt=10),
                _visit("2023-06-01", alt=11),
                _visit("2024-01-01", alt=12),
                _visit("2025-01-01", alt=15),
            ],
            event_dates={"cirrhosis_date": date(2024, 6, 1)},
            final_stage="cirrhosis",
        ),
        _timeline(
            "2",
            [
                _visit("2023-01-01", alt=10),
                _visit("2023-06-01", alt=10),
                _visit("2024-01-01", alt=10),
                _visit("2025-01-01", alt=10),
            ],
        ),
        *[
            _timeline(
                str(index),
                [
                    _visit("2023-01-01", alt=index),
                    _visit("2023-06-01", alt=index + 1),
                    _visit("2024-01-01", alt=index + 2),
                    _visit("2025-01-01", alt=index + 3),
                ],
            )
            for index in range(3, 11)
        ],
    ]
    rows = build_stage_rows(timelines, "fatty_liver", _split(timelines))

    by_group = {row.group_id: row for row in rows if row.as_of == date(2024, 1, 1)}
    assert by_group[timelines[0].group_id].label == "cirrhosis"
    assert by_group[timelines[1].group_id].label == "stay_pre_cirrhosis"
    assert by_group[timelines[0].group_id].max_feature_date <= date(2024, 1, 1)


def test_ad_dementia_event_maps_to_dementia_stage_not_mci():
    from app.services.longitudinal_stage_training import build_stage_rows

    timelines = [
        _timeline(
            str(index),
            [
                _visit("2023-01-01", mmse=28),
                _visit("2023-06-01", mmse=26),
                _visit("2024-01-01", mmse=24),
                _visit("2025-01-01", mmse=20),
            ],
            disease="ad",
            event_dates=(
                {"dementia_date": date(2024, 6, 1)} if index == 1 else {}
            ),
            final_stage="dementia" if index == 1 else "normal",
        )
        for index in range(1, 11)
    ]
    rows = build_stage_rows(timelines, "ad", _split(timelines, "ad"))
    target = next(
        row
        for row in rows
        if row.group_id == timelines[0].group_id
        and row.as_of == date(2024, 1, 1)
    )
    assert target.label == "dementia"


def test_ad_stage_uses_visit_cdr_but_excludes_cdr_from_features():
    from app.services.longitudinal_stage_training import build_stage_rows

    timelines = [
        _timeline(
            str(index),
            [
                _visit("2023-01-01", cdr=0, mmse=29),
                _visit("2023-06-01", cdr=0, mmse=28),
                _visit("2024-01-01", cdr=0.5 if index == 1 else 0, mmse=27),
                _visit("2024-06-01", cdr=1 if index == 1 else 0, mmse=24),
                _visit("2025-01-01", cdr=1 if index == 1 else 0, mmse=23),
            ],
            disease="ad",
            event_dates=(
                {"dementia_date": date(2024, 6, 1)} if index == 1 else {}
            ),
            final_stage="1" if index == 1 else "0",
        )
        for index in range(1, 11)
    ]
    rows = build_stage_rows(timelines, "ad", _split(timelines, "ad"))
    target = next(
        row
        for row in rows
        if row.group_id == timelines[0].group_id
        and row.as_of == date(2024, 1, 1)
    )
    assert target.current_stage == "mci"
    assert target.label == "dementia"
    assert not any(name.startswith("cdr.") for name in target.values)


def test_known_event_inside_window_does_not_require_followup_to_window_end():
    from app.services.longitudinal_stage_training import build_stage_rows

    timelines = [
        _timeline(
            str(index),
            [
                _visit("2023-01-01", alt=10),
                _visit("2023-06-01", alt=12),
                _visit("2024-01-01", alt=14),
                _visit("2024-06-01", alt=18),
            ],
            event_dates=(
                {"cirrhosis_date": date(2024, 6, 1)} if index == 1 else {}
            ),
            final_stage="cirrhosis" if index == 1 else "fatty_liver",
        )
        for index in range(1, 11)
    ]
    rows = build_stage_rows(timelines, "fatty_liver", _split(timelines))
    assert any(
        row.group_id == timelines[0].group_id
        and row.as_of == date(2024, 1, 1)
        and row.label == "cirrhosis"
        for row in rows
    )


def test_fatty_liver_stage_contract_can_preserve_cirrhosis():
    from app.services.longitudinal_stage_training import (
        _output_classes,
        _required_classes,
    )

    assert "stay_cirrhosis" in _required_classes("fatty_liver")
    assert "stay_cirrhosis" in _output_classes("fatty_liver")


def test_stage_training_excludes_label_copy_features():
    from app.services.longitudinal_stage_training import (
        StageTrainingRow,
        build_stage_feature_catalog,
    )

    row = StageTrainingRow(
        disease="fatty_liver",
        group_id="patient.v1." + "1" * 64,
        as_of=date(2024, 1, 1),
        max_feature_date=date(2024, 1, 1),
        current_stage="pre_cirrhosis",
        label="cirrhosis",
        values={"age": 60, "current_stage": "pre_cirrhosis", "alt.last": 12.0},
    )
    catalog = build_stage_feature_catalog([row])
    assert not (
        {"final_stage", "event_dates", "dementia_date", "cirrhosis_date", "hcc_date"}
        & set(catalog.feature_names)
    )


def test_ad_cdr_copy_risk_requires_review():
    from app.services.longitudinal_stage_training import (
        StageTrainingRow,
        audit_stage_label_copy,
    )

    rows = [
        StageTrainingRow(
            disease="ad",
            group_id=f"patient.v1.{index:064x}",
            as_of=date(2024, 1, 1),
            max_feature_date=date(2024, 1, 1),
            current_stage="mci",
            label="dementia" if cdr >= 1 else "stay_mci",
            values={"current_stage": "mci", "cdr.last": cdr},
        )
        for index, cdr in enumerate([0.5, 0.5, 1.0, 1.0], start=1)
    ]
    audit = audit_stage_label_copy(rows)
    assert audit.status == "review_required"
    assert "cdr_label_copy_risk" in audit.reason_codes


def test_stage_training_refuses_missing_required_class(tmp_path):
    from app.services.longitudinal_stage_training import (
        StageTrainingError,
        StageTrainingRow,
        train_stage_candidate,
    )

    rows = [
        StageTrainingRow(
            disease="fatty_liver",
            group_id=f"patient.v1.{index:064x}",
            as_of=date(2024, 1, 1),
            max_feature_date=date(2024, 1, 1),
            current_stage="pre_cirrhosis",
            label="cirrhosis" if index % 2 else "stay_pre_cirrhosis",
            values={"age": 60 + index, "current_stage": "pre_cirrhosis", "alt.last": float(index)},
        )
        for index in range(1, 16)
    ]
    split = _split(
        [
            _timeline(
                str(index),
                [_visit("2023-01-01", alt=1), _visit("2023-06-01", alt=2), _visit("2024-01-01", alt=3), _visit("2025-01-01", alt=4)],
            )
            for index in range(1, 16)
        ]
    )
    with pytest.raises(StageTrainingError, match="stage_class_support_insufficient"):
        train_stage_candidate(rows, split, None, tmp_path, seed=42)


def _stage_candidate_fixture(tmp_path):
    from app.schemas.longitudinal_model_training import DatasetInput
    from app.services.longitudinal_group_split import make_disease_group_split
    from app.services.longitudinal_stage_training import StageTrainingRow

    labels = ["stay_pre_cirrhosis", "cirrhosis", "stay_cirrhosis", "hcc"]
    rows = [
        StageTrainingRow(
            disease="fatty_liver",
            group_id=f"patient.v1.{index:064x}",
            as_of=date(2024, 1, 1),
            max_feature_date=date(2024, 1, 1),
            current_stage="pre_cirrhosis",
            label=labels[index % len(labels)],
            values={
                "age": 50 + index,
                "sex": "female" if index % 2 else "male",
                "current_stage": "pre_cirrhosis",
                "visit_count": 3 + index % 3,
                "alt.last": float(index + (index % 3) * 20),
            },
        )
        for index in range(1, 61)
    ]
    samples = [
        type(
            "SplitSample",
            (),
            {
                "identity": type(
                    "Identity",
                    (),
                    {"disease": "fatty_liver", "group_id": row.group_id},
                )(),
                "label": type("Label", (), {"stage_label": row.label})(),
                "task": "fatty_liver.next_stage",
            },
        )()
        for row in rows
    ]
    split = make_disease_group_split(
        samples,
        "fatty_liver",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    dataset = DatasetInput(
        dataset_dir=str(tmp_path / "dataset"),
        schema_version="longitudinal_fixed_window_dataset.v1",
        manifest_sha256="a" * 64,
        data_content_sha256="b" * 64,
        file_sha256_by_path={
            "fatty_liver/real_train.jsonl": "c" * 64,
            "group_splits.json": "d" * 64,
        },
        group_split_file="group_splits.json",
        group_split_sha256="d" * 64,
    )
    return rows, split, dataset


def test_stage_candidate_reports_ordered_metrics_and_v2_bundle(tmp_path):
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2, EvaluationArtifact
    from app.services.longitudinal_stage_training import (
        train_stage_candidate,
        write_stage_candidate_bundle,
    )

    rows, split, dataset = _stage_candidate_fixture(tmp_path)
    candidate = train_stage_candidate(
        rows, split, dataset, tmp_path / "fit", seed=42
    )
    bundle = write_stage_candidate_bundle(candidate, tmp_path / "bundles")
    metadata = ArtifactMetadataV2.model_validate_json(
        bundle.metadata_path.read_text(encoding="utf-8")
    )
    evaluation = EvaluationArtifact.model_validate_json(
        bundle.evaluation_path.read_text(encoding="utf-8")
    )

    metrics = candidate.locked_test_metrics
    assert metrics.macro_f1 is not None
    assert metrics.balanced_accuracy is not None
    assert metrics.ordered_error is not None
    assert metrics.class_order == metadata.output_contract.classes
    assert metadata.artifact_type == "stage"
    assert metadata.task == "fatty_liver.next_stage"
    assert metadata.split_sha256 == split.sha256
    assert evaluation.locked_test_used_for_selection is False
    assert len(list(bundle.bundle_dir.iterdir())) == 3


def test_stage_locked_test_runs_only_after_candidate_freeze(monkeypatch, tmp_path):
    import app.services.longitudinal_stage_training as training

    rows, split, dataset = _stage_candidate_fixture(tmp_path)
    calls = []
    original = training.evaluate_stage_locked_test

    def record(*args, **kwargs):
        calls.append("locked")
        return original(*args, **kwargs)

    monkeypatch.setattr(training, "evaluate_stage_locked_test", record)
    candidate = training.train_stage_candidate(
        rows, split, dataset, tmp_path / "fit", seed=42
    )

    assert candidate.selection_trace[-1] == "candidate_frozen"
    assert calls == ["locked"]
