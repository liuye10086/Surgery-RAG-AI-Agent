from types import SimpleNamespace
import pytest
from test_synthetic_case_source import case_fixture, service
from app.schemas.longitudinal_case import OperatorCaseOut


def case():
    value, raw = case_fixture()
    value.status = 'active'
    value.disease = SimpleNamespace(id=3, code='ad', name='阿尔茨海默病', operator_enabled=True)
    value.engineering_source = service().build_engineering_binding(value, raw)
    return value


def test_server_projection_exposes_verified_readonly_capability_only(monkeypatch):
    from app.core.config import settings
    for flag in ('SYNTHETIC_REPORTS_ENABLED', 'REPORT_JOBS_ENABLED', 'REPORT_JOBS_ACCEPTING'):
        monkeypatch.setattr(settings, flag, True)
    payload = OperatorCaseOut.model_validate(case()).model_dump(mode='json')
    assert payload['engineering'] == dict(verified=True, input_readonly=True, report_kind='synthetic_numeric', enabled=True)
    assert 'engineering_source' not in payload


@pytest.mark.parametrize('state', ['missing', 'tampered', 'closed'])
def test_untrusted_or_disabled_source_never_exposes_enabled_action(monkeypatch, state):
    from app.core.config import settings
    value = case()
    monkeypatch.setattr(settings, 'SYNTHETIC_REPORTS_ENABLED', state != 'closed')
    if state == 'missing': value.engineering_source = None
    if state == 'tampered': value.age += 1
    result = OperatorCaseOut.model_validate(value).model_dump(mode='json')
    if state == 'missing':
        assert result['engineering'] is None
    else:
        assert result['engineering']['input_readonly'] is True
        assert result['engineering']['enabled'] is False
        assert result['engineering']['verified'] is (state == 'closed')


def test_serialized_client_capability_cannot_forge_trusted_source():
    value = OperatorCaseOut.model_validate(case()).model_dump(mode='json')
    value['engineering'] = dict(verified=True, input_readonly=True, report_kind='synthetic_numeric', enabled=True)
    assert OperatorCaseOut.model_validate(value).engineering is None
