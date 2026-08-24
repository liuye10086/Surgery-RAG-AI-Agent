from pathlib import Path

from app.services.standard_parser import parse_numeric_expression, parse_standard_docx


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
