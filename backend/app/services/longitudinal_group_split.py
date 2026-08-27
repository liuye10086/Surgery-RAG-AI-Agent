"""Deterministic disease-level patient partitions for all longitudinal models."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


GROUP_SPLIT_SCHEMA_VERSION = "longitudinal_disease_group_split.v1"
GROUP_SPLITS_FILE_SCHEMA_VERSION = "longitudinal_disease_group_splits.v1"
PartitionName = Literal[
    "development_train",
    "development_validation",
    "locked_test",
]


class GroupSplitError(ValueError):
    """Stable, privacy-safe group split contract error."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _group_id(sample: Any) -> str:
    value = str(getattr(getattr(sample, "identity", None), "group_id", ""))
    if not value.startswith("patient.v1.") or len(value) != len("patient.v1.") + 64:
        raise GroupSplitError("invalid_group_id")
    return value


def _disease(sample: Any) -> str:
    return str(getattr(getattr(sample, "identity", None), "disease", ""))


def _task_name(sample: Any) -> str:
    explicit = getattr(sample, "task", None)
    if explicit:
        return str(explicit)
    identity = getattr(sample, "identity", None)
    current_state = getattr(identity, "current_state", None)
    target_event = getattr(identity, "target_event", None)
    if current_state is not None or target_event is not None:
        return f"{current_state or 'unknown'}:{target_event or 'unknown'}"
    return "shared"


def _label_value(sample: Any) -> str:
    label = getattr(sample, "label", None)
    for attribute in (
        "training_label",
        "stage_label",
        "trend_label",
        "target",
        "value",
        "status",
    ):
        value = getattr(label, attribute, None)
        if value is not None:
            return str(value)
    raise GroupSplitError("sample_label_missing")


class DiseaseGroupSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["longitudinal_disease_group_split.v1"] = (
        GROUP_SPLIT_SCHEMA_VERSION
    )
    disease: Literal["fatty_liver", "ad"]
    strategy: Literal["deterministic_multilabel_group_stratification"] = (
        "deterministic_multilabel_group_stratification"
    )
    seed: int
    validation_fraction: float = Field(gt=0, lt=1)
    test_fraction: float = Field(gt=0, lt=1)
    development_train_groups: list[str]
    development_validation_groups: list[str]
    locked_test_groups: list[str]
    group_count: int = Field(ge=3)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_partitions(self):
        if self.validation_fraction + self.test_fraction >= 1:
            raise ValueError("invalid_split_fractions")
        partitions = (
            self.development_train_groups,
            self.development_validation_groups,
            self.locked_test_groups,
        )
        if any(not groups for groups in partitions):
            raise ValueError("empty_partition")
        sets = [set(groups) for groups in partitions]
        if any(len(groups) != len(group_set) for groups, group_set in zip(partitions, sets)):
            raise ValueError("duplicate_group")
        if sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2]:
            raise ValueError("group_overlap")
        if sum(len(group_set) for group_set in sets) != self.group_count:
            raise ValueError("group_count_mismatch")
        if any(
            not group.startswith("patient.v1.")
            for group_set in sets
            for group in group_set
        ):
            raise ValueError("invalid_group_id")
        if self.sha256 != _sha256_json(self.hash_payload()):
            raise ValueError("split_hash_mismatch")
        return self

    def hash_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "disease": self.disease,
            "strategy": self.strategy,
            "seed": self.seed,
            "validation_fraction": self.validation_fraction,
            "test_fraction": self.test_fraction,
            "development_train_groups": self.development_train_groups,
            "development_validation_groups": self.development_validation_groups,
            "locked_test_groups": self.locked_test_groups,
            "group_count": self.group_count,
        }

    def assignments(self) -> dict[str, PartitionName]:
        return {
            **{group: "development_train" for group in self.development_train_groups},
            **{
                group: "development_validation"
                for group in self.development_validation_groups
            },
            **{group: "locked_test" for group in self.locked_test_groups},
        }


def _partition_sizes(
    group_count: int,
    validation_fraction: float,
    test_fraction: float,
) -> dict[PartitionName, int]:
    if group_count < 3:
        raise GroupSplitError("insufficient_groups")
    if not 0 < validation_fraction < 1 or not 0 < test_fraction < 1:
        raise GroupSplitError("invalid_split_fractions")
    if validation_fraction + test_fraction >= 1:
        raise GroupSplitError("invalid_split_fractions")
    validation_count = max(1, int(round(group_count * validation_fraction)))
    test_count = max(1, int(round(group_count * test_fraction)))
    if validation_count + test_count >= group_count:
        raise GroupSplitError("insufficient_development_groups")
    return {
        "development_train": group_count - validation_count - test_count,
        "development_validation": validation_count,
        "locked_test": test_count,
    }


def _stable_rank(seed: int, disease: str, *parts: str) -> str:
    payload = "\0".join((str(seed), disease, *parts)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def make_disease_group_split(
    samples: Sequence[Any],
    disease: str,
    *,
    seed: int,
    validation_fraction: float,
    test_fraction: float,
) -> DiseaseGroupSplit:
    if disease not in {"fatty_liver", "ad"}:
        raise GroupSplitError("unsupported_disease")
    scoped = [sample for sample in samples if _disease(sample) == disease]
    if not scoped:
        raise GroupSplitError("disease_samples_missing")

    tokens_by_group: dict[str, set[str]] = defaultdict(set)
    for sample in scoped:
        group = _group_id(sample)
        tokens_by_group[group].add(f"{_task_name(sample)}={_label_value(sample)}")

    capacities = _partition_sizes(
        len(tokens_by_group), validation_fraction, test_fraction
    )
    fractions: dict[PartitionName, float] = {
        "development_train": 1 - validation_fraction - test_fraction,
        "development_validation": validation_fraction,
        "locked_test": test_fraction,
    }
    token_support: dict[str, int] = defaultdict(int)
    for tokens in tokens_by_group.values():
        for token in tokens:
            token_support[token] += 1
    token_targets: dict[PartitionName, dict[str, float]] = {
        partition: {
            token: support * fractions[partition]
            for token, support in token_support.items()
        }
        for partition in capacities
    }
    token_counts: dict[PartitionName, dict[str, int]] = {
        partition: defaultdict(int) for partition in capacities
    }
    assigned: dict[PartitionName, list[str]] = {
        partition: [] for partition in capacities
    }

    groups = sorted(
        tokens_by_group,
        key=lambda group: (
            min(token_support[token] for token in tokens_by_group[group]),
            -len(tokens_by_group[group]),
            _stable_rank(seed, disease, group),
        ),
    )
    partition_order: tuple[PartitionName, ...] = (
        "development_train",
        "development_validation",
        "locked_test",
    )
    for group in groups:
        tokens = tokens_by_group[group]
        candidates = [
            partition
            for partition in partition_order
            if len(assigned[partition]) < capacities[partition]
        ]
        if not candidates:
            raise GroupSplitError("partition_capacity_exhausted")

        def score(partition: PartitionName) -> tuple[float, float, str]:
            deficit = sum(
                max(
                    token_targets[partition][token]
                    - token_counts[partition][token],
                    0.0,
                )
                / token_support[token]
                for token in tokens
            )
            capacity_remaining = (
                capacities[partition] - len(assigned[partition])
            ) / capacities[partition]
            tie_breaker = _stable_rank(seed, disease, group, partition)
            return (deficit, capacity_remaining, tie_breaker)

        selected = max(candidates, key=score)
        assigned[selected].append(group)
        for token in tokens:
            token_counts[selected][token] += 1

    required_partitions = {
        partition for partition, size in capacities.items() if size > 0
    }
    for token, support in token_support.items():
        if support < len(required_partitions):
            continue
        covered = {
            partition
            for partition in required_partitions
            if token_counts[partition][token] > 0
        }
        if covered != required_partitions:
            raise GroupSplitError("class_coverage_unavailable")

    payload = {
        "schema_version": GROUP_SPLIT_SCHEMA_VERSION,
        "disease": disease,
        "strategy": "deterministic_multilabel_group_stratification",
        "seed": seed,
        "validation_fraction": validation_fraction,
        "test_fraction": test_fraction,
        "development_train_groups": sorted(assigned["development_train"]),
        "development_validation_groups": sorted(
            assigned["development_validation"]
        ),
        "locked_test_groups": sorted(assigned["locked_test"]),
        "group_count": len(tokens_by_group),
    }
    return DiseaseGroupSplit(**payload, sha256=_sha256_json(payload))


def materialize_all_task_assignments(
    samples: Iterable[Any],
    split: DiseaseGroupSplit,
) -> dict[str, set[PartitionName]]:
    partition_by_group = split.assignments()
    assignments: dict[str, set[PartitionName]] = defaultdict(set)
    for sample in samples:
        if _disease(sample) != split.disease:
            continue
        group = _group_id(sample)
        try:
            assignments[group].add(partition_by_group[group])
        except KeyError as exc:
            raise GroupSplitError("sample_group_missing_from_split") from exc
    return dict(assignments)


def write_group_splits(
    dataset_dir: Path,
    splits: Sequence[DiseaseGroupSplit],
) -> Path:
    root = Path(dataset_dir)
    if not root.is_dir():
        raise FileNotFoundError(root)
    diseases = [split.disease for split in splits]
    if len(diseases) != len(set(diseases)):
        raise GroupSplitError("duplicate_disease_split")
    payload = {
        "schema_version": GROUP_SPLITS_FILE_SCHEMA_VERSION,
        "splits": [
            split.model_dump(mode="json")
            for split in sorted(splits, key=lambda value: value.disease)
        ],
    }
    path = root / "group_splits.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(_canonical_json(payload) + "\n", encoding="utf-8", newline="")
    return path


def read_disease_group_splits(
    dataset_dir: Path,
) -> dict[str, DiseaseGroupSplit]:
    path = Path(dataset_dir) / "group_splits.json"
    if not path.is_file():
        raise GroupSplitError("group_splits_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GroupSplitError("group_splits_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != GROUP_SPLITS_FILE_SCHEMA_VERSION
        or not isinstance(payload.get("splits"), list)
    ):
        raise GroupSplitError("group_splits_invalid")
    try:
        splits = [DiseaseGroupSplit.model_validate(item) for item in payload["splits"]]
    except Exception as exc:
        raise GroupSplitError("group_splits_invalid") from exc
    result = {split.disease: split for split in splits}
    if len(result) != len(splits):
        raise GroupSplitError("duplicate_disease_split")
    return result
