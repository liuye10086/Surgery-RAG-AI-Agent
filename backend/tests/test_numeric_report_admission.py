from copy import deepcopy

import pytest

from app.services.report_generation_idempotency import hash_report_request
from app.schemas.longitudinal_case import OperatorCaseOut


def test_neutral_request_has_own_identity_and_preserves_old_digest():
    from hashlib import sha256
    import json
    old = sha256(json.dumps({'contract':'report_job_request.v1','case_id':9,'model_options':{}}, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    assert hash_report_request(9, {}) == old
    digest = hash_report_request(9, {'report_kind':'numeric_prediction'})
    assert digest != old and digest != hash_report_request(9, {'report_kind':'synthetic_numeric'})


def test_legacy_source_projects_neutral_capability_without_leaking_source(monkeypatch):
    from test_synthetic_case_capability import case
    from app.core.config import settings
    for flag in ('NUMERIC_REPORTS_ENABLED','REPORT_JOBS_ENABLED','REPORT_JOBS_ACCEPTING'):
        monkeypatch.setattr(settings, flag, True)
    data = OperatorCaseOut.model_validate(case()).model_dump(mode='json')
    assert data['prediction'] == dict(verified=True, input_readonly=True, report_kind='numeric_prediction', enabled=True)
    assert 'prediction_source' not in data and 'engineering_source' not in data
    data['prediction'] = deepcopy(data['prediction'])
    assert OperatorCaseOut.model_validate(data).prediction is None


@pytest.mark.parametrize('state,expected', [('closed','numeric_reports_unavailable'),('tampered','prediction_source_invalid'),('missing','prediction_source_required')])
def test_neutral_admission_rejects_closed_or_unbound_inputs(monkeypatch, state, expected):
    from test_synthetic_case_capability import case
    from app.core.config import settings
    from app.services.numeric_report_admission import build_numeric_snapshot
    from app.services.report_generation_errors import ReportJobError
    monkeypatch.setattr(settings,'NUMERIC_REPORTS_ENABLED', state != 'closed')
    value = case()
    if state == 'tampered': value.age += 1
    if state == 'missing': value.engineering_source = None
    with pytest.raises(ReportJobError) as failure: build_numeric_snapshot(value)
    assert failure.value.code == expected
