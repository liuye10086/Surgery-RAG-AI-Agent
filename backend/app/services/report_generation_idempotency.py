"""Stable request identity independent of subsequent case edits."""

import hashlib
import json

REPORT_SCOPE = "create_longitudinal_report"


def hash_report_request(case_id, request):
    if (
        not isinstance(request, dict)
        or set(request) - {"model_options", "report_kind"}
        or request.get("report_kind", "longitudinal_predictive") not in ("longitudinal_predictive", "synthetic_numeric", "numeric_prediction")
        or request.get("model_options", {}) != {}
    ):
        raise ValueError("unsupported_report_options")
    value = {
        "contract": "report_job_request.v1",
        "case_id": case_id,
        "model_options": {},
    }
    if request.get("report_kind") == "synthetic_numeric":
        value.update(contract="synthetic_numeric_report_job_request.v1", report_kind="synthetic_numeric")
    if request.get("report_kind") == "numeric_prediction":
        value.update(contract="numeric_report_job_request.v1", report_kind="numeric_prediction")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
