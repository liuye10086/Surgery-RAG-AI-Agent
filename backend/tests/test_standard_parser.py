from pathlib import Path

from app.services.standard_parser import (
    build_rule_candidates,
    contains_approximation,
    parse_numeric_expression,
    parse_sex_numeric_expressions,
    parse_standard_docx,
)


FIXTURES = Path(__file__).parent / "fixtures" / "standards"


def test_parse_both_standards_preserves_table_locations():
    ad = parse_standard_docx(FIXTURES / "ad_standard.docx", parser_version="v1")
    fatty = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v1")
    assert len(ad.tables) == 8 and len(fatty.tables) == 4
    assert any(segment.table_index == 5 and segment.row_index == 6 for segment in ad.segments)
    assert any("MAFLD" in segment.raw_text for segment in fatty.segments)


def test_parse_numeric_expression_preserves_open_and_closed_bounds():
    assert parse_numeric_expression("< 1.158").upper_inclusive is False
    assert parse_numeric_expression("≥ 5% ").lower_inclusive is True
    assert parse_numeric_expression("5%\u201310%").lower == 5


def test_build_candidates_keeps_qualitative_text_as_evidence():
    parsed = parse_standard_docx(FIXTURES / "ad_standard.docx", parser_version="v1")
    candidates = parsed.rule_candidates
    assert any(c.machine_actionability == "evidence-only" for c in candidates)
    assert any(c.target_state_type == "stage" for c in candidates)


def test_parser_exposes_pure_candidate_adapter_hook():
    parsed = parse_standard_docx(FIXTURES / "ad_standard.docx", parser_version="v1")
    assert build_rule_candidates(parsed) == parsed.rule_candidates


def test_approximate_text_is_detected_and_never_auto_calculable():
    assert contains_approximation("约 15–40")
    assert contains_approximation("常见为≥26分")
    parsed = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v2")
    ast = next(item for item in parsed.rule_candidates if item.indicator_name.startswith("AST"))
    assert ast.machine_actionability == "evidence-only"
    assert "approximate_language" in ast.parse_warnings


def test_unit_comes_only_from_the_unit_cell_not_explanation_text():
    parsed = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v2")
    tbil = next(item for item in parsed.rule_candidates if item.indicator_name.startswith("TBIL"))
    assert tbil.numeric.unit == "μmol/L"
    assert "不用于脂肪含量分级" not in tbil.numeric.unit


def test_sex_specific_ranges_are_preserved_as_two_candidates():
    expressions = parse_sex_numeric_expressions("男性 < 90；女性 < 85")
    assert [(sex, item.upper, item.upper_inclusive) for sex, item in expressions] == [
        ("male", 90.0, False),
        ("female", 85.0, False),
    ]
    parsed = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v2")
    waist = [item for item in parsed.rule_candidates if item.indicator_name.startswith("WAIST")]
    assert {(item.sex, item.numeric.upper) for item in waist} == {("male", 90.0), ("female", 85.0)}


def test_platform_or_cohort_specific_ad_threshold_is_not_generic_calculable():
    parsed = parse_standard_docx(FIXTURES / "ad_standard.docx", parser_version="v2")
    ptau = next(
        item for item in parsed.rule_candidates
        if item.indicator_name.startswith("Plasma p-tau217") and item.numeric
    )
    assert ptau.machine_actionability == "evidence-only"
    assert "missing_applicability" in ptau.parse_warnings
