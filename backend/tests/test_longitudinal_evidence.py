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
