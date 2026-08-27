from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class SplitFixtureSample:
    identity: SimpleNamespace
    label: SimpleNamespace
    task: str


def _sample(
    group_number: int,
    *,
    disease: str,
    task: str,
    label: int,
) -> SplitFixtureSample:
    group_id = f"patient.v1.{group_number:064x}"
    return SplitFixtureSample(
        identity=SimpleNamespace(
            disease=disease,
            group_id=group_id,
            patient_label=f"PRIVATE-{group_number}",
            source_document=f"private-source-{group_number}.docx",
        ),
        label=SimpleNamespace(training_label=label, status="positive" if label else "negative"),
        task=task,
    )


def _fatty_liver_samples() -> list[SplitFixtureSample]:
    samples: list[SplitFixtureSample] = []
    for number in range(20):
        samples.append(
            _sample(
                number,
                disease="fatty_liver",
                task="fatty_liver.pre_cirrhosis_to_progression",
                label=number % 2,
            )
        )
        samples.append(
            _sample(
                number,
                disease="fatty_liver",
                task="fatty_liver.cirrhosis_to_hcc",
                label=(number // 2) % 2,
            )
        )
    return samples


def test_fatty_liver_tasks_share_one_disease_split():
    from app.services.longitudinal_group_split import make_disease_group_split

    samples = _fatty_liver_samples()
    split = make_disease_group_split(
        samples,
        "fatty_liver",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )

    assignments = split.assignments()
    pre_groups = {
        sample.identity.group_id
        for sample in samples
        if sample.task == "fatty_liver.pre_cirrhosis_to_progression"
    }
    hcc_groups = {
        sample.identity.group_id
        for sample in samples
        if sample.task == "fatty_liver.cirrhosis_to_hcc"
    }

    assert pre_groups == hcc_groups == set(assignments)
    assert set(split.development_train_groups).isdisjoint(split.locked_test_groups)
    assert set(split.development_validation_groups).isdisjoint(split.locked_test_groups)
    assert split.group_count == 20


def test_same_patient_never_crosses_outcome_stage_or_trend_partitions():
    from app.services.longitudinal_group_split import (
        make_disease_group_split,
        materialize_all_task_assignments,
    )

    samples: list[SplitFixtureSample] = []
    for number in range(20):
        for task in ("outcome", "stage", "trend.mmse"):
            samples.append(
                _sample(
                    number,
                    disease="ad",
                    task=task,
                    label=number % 2,
                )
            )

    split = make_disease_group_split(
        samples,
        "ad",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    assignments = materialize_all_task_assignments(samples, split)

    assert all(len(partitions) == 1 for partitions in assignments.values())


def test_split_is_reproducible_stratified_and_seed_scoped():
    from app.services.longitudinal_group_split import make_disease_group_split

    samples = _fatty_liver_samples()
    first = make_disease_group_split(
        samples,
        "fatty_liver",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    repeated = make_disease_group_split(
        list(reversed(samples)),
        "fatty_liver",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    different_seed = make_disease_group_split(
        samples,
        "fatty_liver",
        seed=7,
        validation_fraction=0.2,
        test_fraction=0.2,
    )

    assert first.model_dump(mode="json") == repeated.model_dump(mode="json")
    assert first.sha256 != different_seed.sha256
    for groups in (
        first.development_train_groups,
        first.development_validation_groups,
        first.locked_test_groups,
    ):
        labels = {
            sample.label.training_label
            for sample in samples
            if sample.identity.group_id in groups
            and sample.task == "fatty_liver.pre_cirrhosis_to_progression"
        }
        assert labels == {0, 1}


def test_write_group_splits_contains_only_anonymous_group_ids(tmp_path):
    from app.services.longitudinal_group_split import (
        make_disease_group_split,
        write_group_splits,
    )

    split = make_disease_group_split(
        _fatty_liver_samples(),
        "fatty_liver",
        seed=42,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    path = write_group_splits(tmp_path, [split])
    payload = json.loads(path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)

    assert path == Path(tmp_path) / "group_splits.json"
    assert payload["schema_version"] == "longitudinal_disease_group_splits.v1"
    assert payload["splits"][0]["sha256"] == split.sha256
    assert "PRIVATE-" not in rendered
    assert "private-source" not in rendered
    assert "patient.v1." in rendered
