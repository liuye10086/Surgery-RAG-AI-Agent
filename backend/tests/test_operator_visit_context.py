import pytest


def test_context_accepts_bounded_common_and_ad_fields():
    from app.schemas.operator_visit_context import VisitContext

    context = VisitContext(
        source_type="assessment",
        facility_name="记忆门诊",
        scale_version="MMSE-30",
        assessment_language="zh-CN",
        education_years=12,
        assay_platform="Roche cobas",
    )
    assert context.source_type == "assessment"
    assert context.education_years == 12
    assert context.assay_platform == "Roche cobas"


def test_context_rejects_unknown_fields_and_out_of_range_education():
    from app.schemas.operator_visit_context import VisitContext

    with pytest.raises(ValueError):
        VisitContext(education_years=31)
    with pytest.raises(ValueError):
        VisitContext(untrusted_payload="should not be accepted")
