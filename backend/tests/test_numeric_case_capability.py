from types import SimpleNamespace

import pytest

from test_numeric_prediction import numeric_fixture
from test_synthetic_case_capability import case


@pytest.mark.parametrize('kind', ['synthetic', 'real'])
def test_new_source_projects_capability_and_snapshot(kind, monkeypatch):
    from app.core.config import settings
    from app.schemas.longitudinal_case import OperatorCaseOut
    from app.services.prediction_case_source import build_prediction_binding
    from app.services.numeric_report_admission import build_numeric_snapshot, capture_numeric_context
    from app.services.report_job_repository import context_hash
    value = case()
    value.engineering_source = None
    value.prediction_source = build_prediction_binding(value, numeric_fixture(kind=kind))
    for flag in ('NUMERIC_REPORTS_ENABLED', 'REPORT_JOBS_ENABLED', 'REPORT_JOBS_ACCEPTING'):
        monkeypatch.setattr(settings, flag, True)
    capability = OperatorCaseOut.model_validate(value).prediction
    assert capability.verified and capability.enabled and capability.input_readonly
    snapshot = build_numeric_snapshot(value)
    assert snapshot['source_binding_sha256'] == context_hash(value.prediction_source)
    assert snapshot['numeric_input']['source']['source_kind'] == kind
    assert capture_numeric_context(snapshot).source_binding_sha256 == snapshot['source_binding_sha256']


@pytest.mark.parametrize('source', [{}, {'source_kind': 'real'}])
def test_new_source_is_readonly_even_if_binding_is_invalid(source):
    from app.services.longitudinal_case_service import require_editable_case_input, ArchivedCaseError
    with pytest.raises(ArchivedCaseError, match='只读'):
        require_editable_case_input(SimpleNamespace(prediction_source=source, engineering_source=None))
