from app.services.longitudinal_evidence import mark_synthetic_source
from pathlib import Path
from types import SimpleNamespace


def test_synthetic_reference_case_is_explicitly_marked():
    source = mark_synthetic_source({"patient_label": "P151", "is_synthetic": True})
    assert source["provenance"] == "synthetic"
    assert "合成" in source["display_warning"]


def test_non_synthetic_source_keeps_reference_provenance():
    source = mark_synthetic_source({"patient_label": "real-1", "provenance": "reference"})
    assert source["provenance"] == "reference"
    assert source["is_synthetic"] is False


def test_longitudinal_report_route_wires_reference_and_similar_case_sources():
    source = Path(__file__).parents[1].joinpath("app/api/operator.py").read_text(encoding="utf-8")
    evidence_source = Path(__file__).parents[1].joinpath("app/services/longitudinal_evidence.py").read_text(encoding="utf-8")
    assert "build_reference_range_sources" in source
    assert "select_similar_longitudinal_cases" in source
    assert "mark_synthetic_source" in source
    assert "CaseRecord.confirmed.is_(True)" in evidence_source


def test_reference_ranges_match_case_insensitively_and_skip_sex_specific_unknowns():
    class Query:
        def __init__(self, rows):
            self.rows = rows
        def filter(self, *args, **kwargs):
            return self
        def all(self):
            return self.rows

    rows = [
        SimpleNamespace(indicator_name="ALT", unit="U/L", lower=7, upper=40, lower_inclusive=True, upper_inclusive=True, sex=None),
        SimpleNamespace(indicator_name="ALT", unit="U/L", lower=9, upper=50, lower_inclusive=True, upper_inclusive=True, sex="male"),
    ]
    db = SimpleNamespace(query=lambda model: Query(rows))
    from app.services.longitudinal_evidence import build_reference_range_sources

    sources = build_reference_range_sources(db, ["alt"], patient_sex=None)
    assert len(sources) == 1
    assert sources[0]["indicator"] == "ALT"


def test_reference_sources_include_versioned_rule_provenance():
    rule = SimpleNamespace(
        id=9,
        machine_actionability="calculable",
        applicability={},
        indicator=SimpleNamespace(canonical_key="alt", aliases=[]),
        unit="U/L",
        lower=7,
        upper=40,
        lower_inclusive=True,
        upper_inclusive=True,
        sex=None,
        category=None,
    )
    version = SimpleNamespace(id=12, status="approved", rules=[rule])
    standard = SimpleNamespace(current_version=version)

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return standard

    from app.services.longitudinal_evidence import build_reference_range_sources

    sources = build_reference_range_sources(SimpleNamespace(query=lambda model: Query()), ["ALT"], patient_sex="male", disease_id=2)

    assert {"standard_version_id", "standard_rule_id", "applicability_hash"}.issubset(sources[0])


def test_standard_conflicts_and_unmatched_rules_are_exposed_as_sources(monkeypatch):
    from app.services.longitudinal_evidence import build_reference_range_sources

    resolution = SimpleNamespace(
        version_id=12,
        standard_id=3,
        calculable_rules=[],
        evidence_rules=[],
        unmatched_rules=[SimpleNamespace(id=7, applicability={"platform": "A"})],
        conflicting_rules=[SimpleNamespace(id=8, applicability={"cohort": "X"})],
        warnings=["规则冲突，未自动选择"],
    )
    monkeypatch.setattr("app.services.standard_resolver.resolve_standard_rules", lambda *args, **kwargs: resolution)
    sources = build_reference_range_sources(SimpleNamespace(), ["Aβ42/Aβ40"], disease_id=2)
    assert {item["source_type"] for item in sources} == {"standard_unmatched", "standard_conflict", "standard_warning"}
    assert all(item["standard_version_id"] == 12 for item in sources)


def test_similar_cases_deduplicate_labels_and_merge_overlapping_indicators():
    class Query:
        def filter(self, *args, **kwargs):
            return self
        def limit(self, value):
            return self
        def all(self):
            return [
                SimpleNamespace(patient_label="P001", case_metadata={}, confirmed=True, indicators=[{"name": "ALT"}]),
                SimpleNamespace(patient_label="P001", case_metadata={}, confirmed=True, indicators=[{"name": "AST"}]),
            ]

    db = SimpleNamespace(query=lambda model: Query())
    from app.services.longitudinal_evidence import select_similar_longitudinal_cases
    visits = [{"visit_date": "2024-01-01", "indicators": [{"name": "ALT"}, {"name": "AST"}]}]

    sources = select_similar_longitudinal_cases(db, 1, visits, None)

    assert sources == [{
        "source_type": "similar_case",
        "patient_label": "P001",
        "source_dataset": None,
        "final_outcome": True,
        "overlap_features": ["alt", "ast"],
        "is_synthetic": False,
        "provenance": "reference",
    }]


def test_similar_cases_use_only_explicit_active_data_release():
    class Query:
        def filter(self, *args, **kwargs):
            return self

        def limit(self, value):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    patient_label="legacy",
                    case_metadata={"source_dataset": "longitudinal_300"},
                    confirmed=True,
                    indicators=[{"name": "ALT"}],
                ),
                SimpleNamespace(
                    patient_label="old-release",
                    case_metadata={
                        "logical_dataset": "longitudinal_300",
                        "dataset_release_id": "fl-v1",
                        "dataset_active": False,
                    },
                    confirmed=True,
                    indicators=[{"name": "ALT"}],
                ),
                SimpleNamespace(
                    patient_label="active-release",
                    case_metadata={
                        "logical_dataset": "longitudinal_300",
                        "dataset_release_id": "fl-v2",
                        "dataset_active": True,
                    },
                    confirmed=True,
                    indicators=[{"name": "ALT"}],
                ),
            ]

    db = SimpleNamespace(query=lambda model: Query())
    from app.services.longitudinal_evidence import select_similar_longitudinal_cases

    sources = select_similar_longitudinal_cases(
        db,
        1,
        [{"visit_date": "2024-01-01", "indicators": [{"name": "ALT"}]}],
        SimpleNamespace(dataset="fatty_liver"),
    )

    assert [source["patient_label"] for source in sources] == ["active-release"]
