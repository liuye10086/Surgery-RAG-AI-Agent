import hashlib
import json
from types import SimpleNamespace

import pytest


def test_request_hash_retains_old_bytes_and_separates_numeric_kind():
    from app.services.report_generation_idempotency import hash_report_request
    expected = hashlib.sha256(json.dumps({"contract": "report_job_request.v1", "case_id": 4,
        "model_options": {}}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert hash_report_request(4, {}) == expected
    assert hash_report_request(4, {"report_kind": "longitudinal_predictive"}) == expected
    assert hash_report_request(4, {"report_kind": "synthetic_numeric"}) != expected


@pytest.mark.parametrize("payload", [{"report_kind": None}, {"report_kind": "other"},
    {"report_kind": "synthetic_numeric", "model_options": {"model": "ridge"}},
    {"report_kind": "synthetic_numeric", "source": {}}])
def test_request_rejects_unsupported_options(payload):
    from app.services.report_generation_idempotency import hash_report_request
    with pytest.raises(ValueError):
        hash_report_request(1, payload)


def test_engineering_input_is_readonly_but_ordinary_case_is_editable():
    from app.services.longitudinal_case_service import require_editable_case_input, ArchivedCaseError
    require_editable_case_input(SimpleNamespace(engineering_source=None))
    for binding in ({}, {"source_kind": "synthetic"}):
        with pytest.raises(ArchivedCaseError, match="合成"):
            require_editable_case_input(SimpleNamespace(engineering_source=binding))


def test_job_request_accepts_explicit_kind_and_keeps_old_default():
    from app.api.operator_report_jobs import JobRequest
    assert JobRequest.model_validate({}).report_kind == "longitudinal_predictive"
    assert JobRequest.model_validate({"report_kind": "synthetic_numeric"}).report_kind == "synthetic_numeric"
