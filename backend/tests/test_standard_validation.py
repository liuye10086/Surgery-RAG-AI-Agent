from types import SimpleNamespace

import pytest

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
    version = SimpleNamespace(
        id=3,
        rules=[],
        standard=SimpleNamespace(
            disease=SimpleNamespace(code="fatty_liver", name="脂肪肝（展示名已修改）")
        ),
    )

    class Query:
        def filter(self, *args, **kwargs): return self
        def first(self): return version

    report = validate_version(SimpleNamespace(query=lambda model: Query()), 3)
    assert {item.code for item in report.errors} == {"formal_rules_missing", "calculable_rules_missing"}


def test_validate_version_public_api_uses_stable_ad_code_after_display_name_changes():
    version = SimpleNamespace(
        id=3,
        rules=[
            SimpleNamespace(
                machine_actionability="evidence-only",
                rule_type="qualitative_direction",
                lower=None,
                upper=None,
                unit=None,
                applicability={},
                conditions={},
                target_state_type="evidence",
                clinical_dimension="cognition",
                framework=None,
                biomarker_axis=None,
                stage=None,
                indicator=SimpleNamespace(
                    canonical_key="mmse",
                    abnormal_direction="ordinal_low",
                    allows_numeric_comparison=False,
                ),
                source_segment=None,
            )
        ],
        standard=SimpleNamespace(
            disease=SimpleNamespace(code="ad", name="AD（展示名已修改）")
        ),
    )

    class Query:
        def filter(self, *args, **kwargs): return self
        def first(self): return version

    report = validate_version(SimpleNamespace(query=lambda model: Query()), 3)

    assert report.can_publish is True
    assert "calculable_rules_missing" not in {item.code for item in report.errors}


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


def test_ad_evidence_only_version_can_publish_without_projection():
    report = validate_version_rules([
        _rule(
            machine_actionability="evidence-only",
            rule_type="qualitative_direction",
            lower=None,
            upper=None,
            unit=None,
            indicator=SimpleNamespace(
                canonical_key="mmse",
                data_type="ordinal",
                allows_numeric_comparison=False,
                abnormal_direction="ordinal_low",
            ),
        )
    ], disease_key="ad", require_calculable=False)

    assert report.errors == []
    assert report.calculable_rule_count == 0
    assert report.projection_count == 0
    assert report.can_publish


def test_ad_evidence_only_exception_does_not_allow_empty_or_blocked_versions():
    empty = validate_version_rules([], disease_key="ad", require_calculable=False)
    assert not empty.can_publish
    assert "formal_rules_missing" in {item.code for item in empty.errors}

    blocked = validate_version_rules([
        _rule(
            machine_actionability="blocked",
            rule_type="qualitative_direction",
            lower=None,
            upper=None,
            unit=None,
        )
    ], disease_key="ad", require_calculable=False)
    assert not blocked.can_publish
    assert blocked.blocked_rule_count == 1


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


def test_reviewed_fatty_approximate_range_is_calculable_with_complete_provenance():
    result = validate_rule(_rule(
        indicator=SimpleNamespace(
            canonical_key="ast",
            data_type="numeric",
            allows_numeric_comparison=True,
            abnormal_direction="high",
        ),
        source_segment=SimpleNamespace(raw_text="AST 约 15–40 U/L"),
        lower=15,
        upper=40,
        lower_inclusive=True,
        upper_inclusive=True,
        unit="U/L",
        applicability={
            "source_language": "approximate",
            "approximate_boundary_policy": "owner_reviewed_strict",
            "_manifest_entry_id": "fatty-ast-reference",
            "_manifest_sha256": "a" * 64,
            "_manifest_reviewed_at": "2026-08-26T01:14:26Z",
        },
    ), disease_key="fatty_liver")
    assert result.actionability == "calculable"
    assert "approximate_calculable_rule" not in {item.code for item in result.errors}


def test_reviewed_approximate_override_requires_complete_manifest_provenance():
    result = validate_rule(_rule(
        indicator=SimpleNamespace(
            canonical_key="ast",
            data_type="numeric",
            allows_numeric_comparison=True,
            abnormal_direction="high",
        ),
        source_segment=SimpleNamespace(raw_text="AST 约 15–40 U/L"),
        lower=15,
        upper=40,
        lower_inclusive=True,
        upper_inclusive=True,
        unit="U/L",
        applicability={
            "source_language": "approximate",
            "approximate_boundary_policy": "owner_reviewed_strict",
            "_manifest_entry_id": "fatty-ast-reference",
            "_manifest_sha256": "a" * 64,
        },
    ), disease_key="fatty_liver")
    assert "approximate_calculable_rule" in {item.code for item in result.errors}


@pytest.mark.parametrize("key", ["bmi", "mmse"])
def test_reviewed_approximate_override_does_not_apply_to_other_indicators(key: str):
    result = validate_rule(_rule(
        indicator=SimpleNamespace(
            canonical_key=key,
            data_type="numeric",
            allows_numeric_comparison=True,
            abnormal_direction="high" if key == "bmi" else "ordinal_low",
        ),
        source_segment=SimpleNamespace(raw_text=f"{key} 约 15–40"),
        lower=15,
        upper=40,
        lower_inclusive=True,
        upper_inclusive=True,
        unit="points" if key == "mmse" else "kg/m²",
        applicability={
            "source_language": "approximate",
            "approximate_boundary_policy": "owner_reviewed_strict",
            "_manifest_entry_id": f"reviewed-{key}",
            "_manifest_sha256": "a" * 64,
            "_manifest_reviewed_at": "2026-08-26T01:14:26Z",
        },
    ), disease_key="fatty_liver" if key == "bmi" else "ad")
    assert "approximate_calculable_rule" in {item.code for item in result.errors}


def test_context_incomplete_calculable_rule_is_rejected():

    ptau = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="p-tau217", data_type="numeric", allows_numeric_comparison=True, abnormal_direction="high"),
        unit="pg/mL",
        applicability={},
    ), disease_key="ad")
    assert "ad_biomarker_applicability_missing" in {item.code for item in ptau.errors}
