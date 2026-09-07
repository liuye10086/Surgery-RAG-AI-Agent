from app.services.report_evidence_presentation import build_evidence_section
from backend.tests.test_evidence_bundle_service import _bundle


def test_presentation_keeps_document_provenance_and_all_rules():
    bundle = _bundle()
    section = build_evidence_section(bundle)
    text = str(section.model_dump())
    assert section.number == 8
    assert bundle.standard.document.title in text
    assert bundle.standard.version.version_label in text
    for rule in bundle.standard.rules:
        assert rule.source.raw_text in text
    assert "不代表当前病例将发生相同结局" in text
