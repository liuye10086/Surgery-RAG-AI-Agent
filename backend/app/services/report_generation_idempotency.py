"""Stable request identity independent of subsequent case edits."""

import hashlib
import json

REPORT_SCOPE = "create_longitudinal_report"


def hash_report_request(case_id, request):
    if (
        not isinstance(request, dict)
        or set(request) - {"model_options"}
        or request.get("model_options", {}) != {}
    ):
        raise ValueError("unsupported_report_options")
    value = {
        "contract": "report_job_request.v1",
        "case_id": case_id,
        "model_options": {},
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
