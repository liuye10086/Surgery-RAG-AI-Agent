"""Model-manifest-driven report readiness for operator cases."""

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _visit(day: str, *, disease="fatty_liver"):
    indicator = (
        {"name": "ALT", "value": 42, "unit": "U/L"}
        if disease == "fatty_liver"
        else {"name": "MMSE", "value": 24, "unit": "分"}
    )
    return SimpleNamespace(
        visit_date=date.fromisoformat(day),
        indicators=[indicator],
        notes=None,
    )


def _case(*, count=3, disease="fatty_liver", stage=None, **overrides):
    default_stage = "pre_cirrhosis" if disease == "fatty_liver" else "mci"
    values = {
        "id": 3,
        "user_id": 7,
        "disease_id": 11,
        "age": 56,
        "sex": "male",
        "baseline_stage": stage or default_stage,
        "status": "active",
        "disease": SimpleNamespace(
            id=11,
            code=disease,
            operator_enabled=True,
        ),
        "visits": [
            _visit(f"2026-{month:02d}-01", disease=disease)
            for month in range(1, count + 1)
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _evaluate(case):
    from app.services.operator_case_readiness import evaluate_operator_case_readiness

    with patch(
        "app.services.operator_case_readiness.load_active_minimum_visits",
        return_value=3,
    ), patch(
        "app.services.operator_case_readiness.load_active_model_registry",
        return_value=object(),
    ):
        return evaluate_operator_case_readiness(case)


def test_checked_in_active_release_supplies_minimum_visits_without_fallback():
    from app.services.operator_case_readiness import load_active_minimum_visits

    assert load_active_minimum_visits("fatty_liver") == 3
    assert load_active_minimum_visits("ad") == 3


@pytest.mark.parametrize(
    ("count", "ready"),
    [(1, False), (2, False), (3, True)],
)
def test_readiness_separates_case_save_count_from_model_threshold(count: int, ready: bool):
    result = _evaluate(_case(count=count))

    assert result.visit_count == count
    assert result.minimum_visits == 3
    assert result.case_ready is True
    assert result.timeline_ready is ready
    assert result.ready is ready
    assert ("insufficient_visits" in {item.code for item in result.blockers}) is (not ready)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"age": None}, "case_incomplete"),
        ({"sex": None}, "case_incomplete"),
        ({"baseline_stage": None}, "case_incomplete"),
        ({"status": "archived"}, "case_archived"),
    ],
)
def test_incomplete_or_archived_case_has_stable_blocker(overrides, code: str):
    result = _evaluate(_case(**overrides))

    assert result.ready is False
    assert code in {item.code for item in result.blockers}


def test_definite_terminal_stage_can_be_saved_but_report_is_not_applicable():
    result = _evaluate(_case(stage="hcc"))

    assert result.case_ready is True
    assert result.ready is False
    assert "prediction_not_applicable" in {item.code for item in result.blockers}


def test_model_failure_has_no_hard_coded_minimum_fallback():
    from app.services.operator_case_readiness import evaluate_operator_case_readiness

    with patch(
        "app.services.operator_case_readiness.load_active_minimum_visits",
        side_effect=RuntimeError("manifest unavailable"),
    ):
        result = evaluate_operator_case_readiness(_case())

    assert result.ready is False
    assert result.model_ready is False
    assert result.minimum_visits is None
    assert "model_unavailable" in {item.code for item in result.blockers}


def test_catalog_failure_blocks_report_readiness_without_crashing_case_read():
    from app.services.operator_case_readiness import evaluate_operator_case_readiness
    from app.services.operator_indicator_catalog import IndicatorCatalogUnavailableError

    with patch(
        "app.services.operator_case_readiness.normalize_operator_timeline",
        side_effect=IndicatorCatalogUnavailableError("private path"),
    ), patch(
        "app.services.operator_case_readiness.load_active_minimum_visits",
        return_value=3,
    ):
        result = evaluate_operator_case_readiness(_case())

    assert result.ready is False
    assert result.timeline_ready is False
    assert "indicator_catalog_unavailable" in {item.code for item in result.blockers}


def test_manifest_hash_mismatch_is_rejected(tmp_path: Path):
    from app.services.operator_case_readiness import (
        OperatorCaseReadinessError,
        load_active_minimum_visits,
    )

    manifest_path = tmp_path / "datasets" / "dataset-1" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"minimum_visits": 3}), encoding="utf-8")
    release = SimpleNamespace(
        data_release_id="dataset-1",
        dataset_manifest_sha256=hashlib.sha256(b"different").hexdigest(),
    )
    with patch(
        "app.services.operator_case_readiness.load_disease_release_set",
        return_value=release,
    ):
        with pytest.raises(OperatorCaseReadinessError) as caught:
            load_active_minimum_visits("fatty_liver", tmp_path)

    assert caught.value.code == "dataset_manifest_hash_mismatch"
