from types import SimpleNamespace

from app.services.standard_resolver import resolve_standard_rules


def _db(standard):
    class Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return standard

    return SimpleNamespace(query=lambda model: Query())


def test_resolver_rejects_missing_platform_context():
    rule = SimpleNamespace(
        id=1,
        machine_actionability="calculable",
        applicability={"platform": "FDG-PET"},
        indicator=SimpleNamespace(canonical_key="fdg-pet suvr", aliases=[]),
    )
    version = SimpleNamespace(id=4, status="approved", rules=[rule])
    standard = SimpleNamespace(current_version=version)

    result = resolve_standard_rules(_db(standard), 2, ["FDG-PET SUVR"], {})

    assert result.calculable_rules == []
    assert result.evidence_rules[0].machine_actionability == "evidence-only"
    assert any("platform" in warning for warning in result.warnings)


def test_resolver_selects_matching_study_without_merging_thresholds():
    delcode = SimpleNamespace(
        id=10,
        machine_actionability="calculable",
        applicability={"cohort": "DELCODE"},
        indicator=SimpleNamespace(canonical_key="csf aβ42/aβ40", aliases=["CSF Aβ42/Aβ40"]),
    )
    adni = SimpleNamespace(
        id=11,
        machine_actionability="calculable",
        applicability={"cohort": "ADNI"},
        indicator=SimpleNamespace(canonical_key="csf aβ42/aβ40", aliases=[]),
    )
    version = SimpleNamespace(id=5, status="approved", rules=[delcode, adni])

    result = resolve_standard_rules(_db(SimpleNamespace(current_version=version)), 2, ["CSF Aβ42/Aβ40"], {"cohort": "DELCODE"})

    assert [rule.id for rule in result.calculable_rules] == [10]
    assert result.evidence_rules == []


def test_resolver_exposes_version_and_rule_provenance():
    rule = SimpleNamespace(
        id=7,
        machine_actionability="calculable",
        applicability={},
        indicator=SimpleNamespace(canonical_key="alt", aliases=[]),
        unit="U/L",
        lower=7,
        upper=40,
        lower_inclusive=True,
        upper_inclusive=True,
    )
    version = SimpleNamespace(id=8, status="approved", rules=[rule])
    result = resolve_standard_rules(_db(SimpleNamespace(current_version=version)), 2, ["ALT"], {})

    assert result.version_id == 8
    assert result.calculable_rules[0].standard_rule_id == 7


def test_resolver_ignores_manifest_audit_metadata_but_keeps_clinical_applicability():
    rule = SimpleNamespace(
        id=12,
        machine_actionability="calculable",
        applicability={
            "source_language": "approximate",
            "approximate_boundary_policy": "owner_reviewed_strict",
            "_manifest_entry_id": "fatty-alt-male-reference",
            "_manifest_sha256": "a" * 64,
            "_manifest_reviewed_at": "2026-08-26T01:14:26+00:00",
        },
        indicator=SimpleNamespace(canonical_key="alt", aliases=[]),
        conflict_group=None,
    )
    version = SimpleNamespace(id=8, status="approved", rules=[rule])

    result = resolve_standard_rules(
        _db(SimpleNamespace(id=3, current_version=version)),
        2,
        ["ALT"],
        {},
    )

    assert [item.standard_rule_id for item in result.calculable_rules] == [12]
    assert result.evidence_rules == []


def test_ad_scale_rule_requires_education_language_and_scale_version():
    rule = SimpleNamespace(
        id=20,
        machine_actionability="calculable",
        applicability={"education": "college", "language": "zh-CN", "scale_version": "MMSE-30"},
        indicator=SimpleNamespace(canonical_key="mmse", aliases=[]),
        conflict_group=None,
    )
    version = SimpleNamespace(id=8, status="approved", rules=[rule])
    result = resolve_standard_rules(_db(SimpleNamespace(id=3, current_version=version)), 2, ["MMSE"], {"education": "college"})
    assert result.calculable_rules == []
    assert result.evidence_rules[0].resolution_warning == "缺少适用条件：language, scale_version"


def test_conflicting_matching_thresholds_are_not_auto_selected():
    first = SimpleNamespace(id=30, machine_actionability="calculable", applicability={"cohort": "DELCODE"}, conflict_group="ab-ratio-cohort", indicator=SimpleNamespace(canonical_key="aβ42/aβ40", aliases=[]))
    second = SimpleNamespace(id=31, machine_actionability="calculable", applicability={"cohort": "DELCODE"}, conflict_group="ab-ratio-cohort", indicator=SimpleNamespace(canonical_key="aβ42/aβ40", aliases=[]))
    version = SimpleNamespace(id=9, status="approved", rules=[first, second])
    result = resolve_standard_rules(_db(SimpleNamespace(id=3, current_version=version)), 2, ["Aβ42/Aβ40"], {"cohort": "DELCODE"})
    assert result.calculable_rules == []
    assert {item.id for item in result.conflicting_rules} == {30, 31}
    assert any("冲突" in warning for warning in result.warnings)


def test_resolver_rejects_current_version_from_another_standard():
    version = SimpleNamespace(id=9, standard_id=99, status="approved", rules=[])
    standard = SimpleNamespace(id=3, current_version=version)
    result = resolve_standard_rules(_db(standard), 2, ["ALT"], {})
    assert result.version_id is None
    assert "归属异常" in result.warnings[0]
