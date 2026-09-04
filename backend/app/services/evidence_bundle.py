"""Canonicalization and integrity helpers for EvidenceBundle v1."""

from __future__ import annotations

import hashlib
import hmac
import json

from app.schemas.longitudinal_evidence import EvidenceBundle


def canonicalize_evidence_bundle(bundle: EvidenceBundle) -> bytes:
    payload = bundle.model_dump(mode="json")
    payload["integrity"]["evidence_snapshot_sha256"] = None
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def finalize_evidence_bundle(bundle: EvidenceBundle) -> EvidenceBundle:
    digest = hashlib.sha256(canonicalize_evidence_bundle(bundle)).hexdigest()
    integrity = bundle.integrity.model_copy(update={"evidence_snapshot_sha256": digest})
    return bundle.model_copy(update={"integrity": integrity})


def verify_evidence_bundle(bundle: EvidenceBundle) -> bool:
    declared = bundle.integrity.evidence_snapshot_sha256
    if declared is None:
        return False
    actual = hashlib.sha256(canonicalize_evidence_bundle(bundle)).hexdigest()
    return hmac.compare_digest(declared, actual)


__all__ = [
    "canonicalize_evidence_bundle",
    "finalize_evidence_bundle",
    "verify_evidence_bundle",
]
