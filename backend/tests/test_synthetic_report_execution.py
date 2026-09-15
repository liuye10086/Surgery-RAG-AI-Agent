from datetime import datetime, timezone

import pytest

from test_synthetic_report_publication import publication_fixture, build_fixture
from app.services.report_integrity import compute_input_snapshot_sha256
from app.services.report_job_repository import context_hash
from app.workers.report_execution import execute_report
from app.workers.report_process_control import supervise_execution


def payload_fixture(unavailable=False):
    snapshot, context, _ = publication_fixture(unavailable=unavailable)
    return dict(report_id=7, created_at=datetime(2026, 9, 14, tzinfo=timezone.utc).isoformat(),
                snapshot=snapshot, snapshot_sha256=compute_input_snapshot_sha256(snapshot),
                context=context, context_sha256=context_hash(context), registry_root='unused')


def test_numeric_execution_never_loads_clinical_models_or_evidence(monkeypatch):
    from app.workers import report_execution
    def forbidden(*a, **kw):
        raise AssertionError('unexpected clinical operation')
    monkeypatch.setattr(report_execution, 'load_pinned_model_suite', forbidden)
    monkeypatch.setattr(report_execution, 'build_pinned_evidence', forbidden)
    monkeypatch.setattr(report_execution, 'run_audited_prediction', forbidden)
    messages = []
    execute_report(payload_fixture(), messages.append)
    assert messages[-1]['kind'] == 'publication'
    events = [m['audit'] for m in messages if m['kind'] == 'audit']
    assert [e['kind'] for e in events] == ['task_finished', 'task_finished', 'evidence_resolved']
    assert events[-1]['result_state'] == 'not_requested'


def test_unavailable_input_crosses_real_process_boundary_without_filled_value():
    result = supervise_execution(execute_report, payload_fixture(unavailable=True),
        maximum_seconds=15, lease_check=lambda: True, on_phase=lambda _: True, phase_limits={})
    assert result.code is None and not result.child_alive
    assert result.publication.generation_fingerprint_version == 'v3'
    assert all(p['value'] is None and p['status'] == 'unavailable'
               for p in result.publication.prediction_result['predictions'])


def publication_target(payload, send):
    send({'kind': 'publication', 'phase': 'persistence', 'publication': payload['publication']})


def test_parent_rejects_numeric_publication_in_clinical_execution():
    _, publication = build_fixture()
    result = supervise_execution(publication_target,
        {'context': {'schema_version': 'report_generation_context.v1'}, 'publication': publication.model_dump(mode='json')},
        maximum_seconds=15, lease_check=lambda: True, on_phase=lambda _: True, phase_limits={})
    assert result.code == 'execution_protocol_invalid'
    assert result.publication is None and not result.child_alive


@pytest.mark.parametrize('part', ['snapshot_sha256', 'context_sha256'])
def test_outer_payload_hash_mismatch_never_executes(part):
    payload = payload_fixture()
    payload[part] = '0' * 64
    messages = []
    execute_report(payload, messages.append)
    assert messages == [{'kind': 'error', 'phase': 'model_loading', 'code': 'generation_context_integrity_failed'}]
