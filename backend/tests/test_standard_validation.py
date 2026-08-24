from types import SimpleNamespace

from app.services.standard_validation import validate_rule, validate_condition_payload
from app.schemas.standard import RulePatch


def test_incomplete_platform_threshold_is_not_calculable():
    report = validate_rule(
        SimpleNamespace(
            rule_type="threshold",
            lower=None,
            upper=1.158,
            unit="",
            applicability={},
            machine_actionability="calculable",
            target_state_type="disease",
            clinical_dimension="imaging",
            indicator=None,
            framework=None,
            conditions={},
        )
    )
    assert report.errors == []
    assert report.actionability == "evidence-only"


def test_fatty_liver_dimensions_cannot_be_mixed():
    report = validate_rule(
        SimpleNamespace(
            rule_type="composite",
            lower=None,
            upper=None,
            unit=None,
            applicability={},
            machine_actionability="calculable",
            target_state_type="grade",
            clinical_dimension="steatosis",
            indicator=None,
            framework=None,
            conditions={"child_dimensions": ["steatosis", "fibrosis_risk"]},
        )
    )
    assert any(item.code == "mixed_clinical_dimensions" for item in report.errors)


def test_condition_tree_rejects_cycles_and_invalid_at_least_n():
    condition = {"node_type": "at_least_n", "payload": {"n": 3}, "children": [{"node_type": "leaf", "payload": {}}]}
    report = validate_condition_payload(condition)
    assert any(item.code == "invalid_cardinality" for item in report.errors)
