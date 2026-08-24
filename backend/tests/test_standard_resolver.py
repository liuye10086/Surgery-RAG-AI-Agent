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
