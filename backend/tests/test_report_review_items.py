from backend.tests.report_document_fixtures import build_demo_document
from app.services.report_review_items import build_review_items


def test_review_items_are_specific_and_deduplicated():
    doc = build_demo_document("ad")
    assert doc.review_items
    for item in doc.review_items:
        assert item.message and item.impact and item.action
        assert item.task or item.indicator or item.field or item.source == "reference"
    assert build_review_items(doc.review_items * 2) == doc.review_items
