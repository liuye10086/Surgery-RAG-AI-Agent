from types import SimpleNamespace

from app.services.standard_validation import (
    build_condition_tree,
    is_projection_eligible,
    validate_condition_payload,
    validate_rule,
    validate_version,
    validate_version_rules,
)
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


def test_build_condition_tree_returns_nested_orm_nodes():
    payload = {"node_type": "all", "payload": {}, "children": [{"node_type": "leaf", "payload": {"sex": "male"}}]}
    root = build_condition_tree(payload)
    assert root.node_type == "all"
    assert root.children[0].node_type == "leaf"


def test_validate_version_public_api_loads_version_rules():
    version = SimpleNamespace(id=3, rules=[])

    class Query:
        def filter(self, *args, **kwargs): return self
        def first(self): return version

    report = validate_version(SimpleNamespace(query=lambda model: Query()), 3)
    assert {item.code for item in report.errors} == {"formal_rules_missing", "calculable_rules_missing"}


def _rule(**updates):
    values = {
        "rule_type": "numeric_range",
        "lower": 7.0,
        "upper": 40.0,
        "unit": "U/L",
        "applicability": {},
        "machine_actionability": "calculable",
        "target_state_type": "control",
        "clinical_dimension": "liver_injury",
        "framework": None,
        "biomarker_axis": None,
        "stage": None,
        "conditions": {},
        "indicator": SimpleNamespace(
            canonical_key="alt",
            data_type="numeric",
            allows_numeric_comparison=True,
            abnormal_direction="high",
        ),
        "source_segment": SimpleNamespace(raw_text="ALT 7–40 U/L"),
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_empty_or_zero_calculable_version_cannot_publish():
    empty = validate_version_rules([], disease_key="fatty_liver")
    assert not empty.can_publish
    assert {item.code for item in empty.errors} == {"formal_rules_missing", "calculable_rules_missing"}

    evidence = validate_version_rules([
        _rule(machine_actionability="evidence-only", rule_type="qualitative_direction", lower=None, upper=None, unit=None)
    ], disease_key="fatty_liver")
    assert not evidence.can_publish
    assert "calculable_rules_missing" in {item.code for item in evidence.errors}


def test_evidence_only_and_non_numeric_calculable_rules_do_not_project():
    assert not is_projection_eligible(_rule(machine_actionability="evidence-only"))
    assert not is_projection_eligible(_rule(rule_type="classification"))
    assert is_projection_eligible(_rule())


def test_ad_directions_are_indicator_specific():
    mmse = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="mmse", data_type="ordinal", allows_numeric_comparison=True, abnormal_direction="high"),
        unit="points",
    ), disease_key="ad")
    assert "invalid_ad_direction" in {item.code for item in mmse.errors}

    cdr = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="cdr", data_type="ordinal", allows_numeric_comparison=True, abnormal_direction="ordinal_high"),
        rule_type="classification",
        lower=None,
        upper=None,
        unit=None,
        conditions={"node_type": "leaf", "payload": {"score": 0.5}},
    ), disease_key="ad")
    assert "invalid_ad_direction" not in {item.code for item in cdr.errors}


def test_approximate_or_context_incomplete_calculable_rule_is_rejected():
    approximate = validate_rule(_rule(
        source_segment=SimpleNamespace(raw_text="AST 约 15–40 U/L")
    ), disease_key="fatty_liver")
    assert "approximate_calculable_rule" in {item.code for item in approximate.errors}

    ptau = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="p-tau217", data_type="numeric", allows_numeric_comparison=True, abnormal_direction="high"),
        unit="pg/mL",
        applicability={},
    ), disease_key="ad")
    assert "ad_biomarker_applicability_missing" in {item.code for item in ptau.errors}
