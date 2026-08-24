from app.services.longitudinal_evidence import mark_synthetic_source


def test_synthetic_reference_case_is_explicitly_marked():
    source = mark_synthetic_source({"patient_label": "P151", "is_synthetic": True})
    assert source["provenance"] == "synthetic"
    assert "合成" in source["display_warning"]


def test_non_synthetic_source_keeps_reference_provenance():
    source = mark_synthetic_source({"patient_label": "real-1", "provenance": "reference"})
    assert source["provenance"] == "reference"
    assert source["is_synthetic"] is False
