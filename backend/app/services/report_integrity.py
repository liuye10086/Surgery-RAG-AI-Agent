"""Stable integrity identifiers for persisted operator reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Any


_DECLARATION_KEYS = {"input_snapshot_sha256"}


@dataclass(frozen=True)
class IntegrityVerificationResult:
    status: str
    reason_code: str
    input_snapshot_valid: bool | None
    generation_fingerprint_valid: bool | None
    evidence_valid: bool | None = None


def _normalize(value: Any, *, drop_hash_declaration: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(item, drop_hash_declaration=drop_hash_declaration)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not (drop_hash_declaration and str(key) in _DECLARATION_KEYS)
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item, drop_hash_declaration=drop_hash_declaration) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def canonicalize_snapshot(snapshot: dict[str, Any]) -> bytes:
    normalized = _normalize(snapshot, drop_hash_declaration=True)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_input_snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_snapshot(snapshot)).hexdigest()


def create_generation_fingerprint(
    snapshot: dict[str, Any], prediction_result: dict[str, Any], content: str,
    evidence_snapshot: dict[str, Any] | None = None,
) -> str:
    payload = {
        "input_snapshot": _normalize(snapshot, drop_hash_declaration=True),
        "prediction_result": _normalize(prediction_result),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    # Preserve the exact pre-EvidenceBundle fingerprint for existing reports.
    # New reports always pass their immutable evidence snapshot explicitly.
    if evidence_snapshot is not None:
        payload["evidence_snapshot"] = _normalize(evidence_snapshot)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_report_integrity(
    input_snapshot: dict[str, Any] | None,
    input_snapshot_sha256: str | None,
    generation_fingerprint: str | None,
    prediction_result: dict[str, Any] | None,
    content: str | None,
    evidence_snapshot: dict[str, Any] | None = None,
    evidence_sha256: str | None = None,
) -> IntegrityVerificationResult:
    evidence_valid = None
    if evidence_snapshot is not None:
        from app.schemas.longitudinal_evidence import EvidenceBundle
        from app.services.evidence_bundle import verify_evidence_bundle
        try:
            bundle = EvidenceBundle.model_validate(evidence_snapshot)
            evidence_valid = verify_evidence_bundle(bundle)
        except Exception:
            evidence_valid = False
        if evidence_sha256 and evidence_snapshot.get("integrity", {}).get("evidence_snapshot_sha256") != evidence_sha256:
            evidence_valid = False
        if not evidence_valid:
            return IntegrityVerificationResult("invalid", "evidence_integrity_mismatch", None, None, False)
    if not input_snapshot_sha256 or not generation_fingerprint:
        return IntegrityVerificationResult(
            "unverifiable", "legacy_missing_integrity_fields", None, None,
            evidence_valid,
        )
    if not isinstance(input_snapshot, dict) or not isinstance(prediction_result, dict) or content is None:
        return IntegrityVerificationResult("invalid", "integrity_input_missing", False, False, evidence_valid)
    input_valid = compute_input_snapshot_sha256(input_snapshot) == input_snapshot_sha256
    fingerprint_valid = create_generation_fingerprint(input_snapshot, prediction_result, content, evidence_snapshot) == generation_fingerprint
    if input_valid and fingerprint_valid:
        return IntegrityVerificationResult("valid", "integrity_verified", True, True, evidence_valid)
    return IntegrityVerificationResult("invalid", "integrity_mismatch", input_valid, fingerprint_valid, evidence_valid)
