import hashlib
import json

from app.services.report_integrity import (
    canonicalize_snapshot,
    compute_input_snapshot_sha256,
    create_generation_fingerprint,
    verify_report_integrity,
)


def test_generation_fingerprint_changes_when_evidence_changes():
    snapshot = {"case": 1}
    prediction = {"risk": 0.2}
    first = create_generation_fingerprint(snapshot, prediction, "正文", {"evidence": "a"})
    second = create_generation_fingerprint(snapshot, prediction, "正文", {"evidence": "b"})
    assert first != second


def test_snapshot_hash_is_stable_for_mapping_key_order():
    first = {"age": 60, "visits": [{"visit_date": "2024-01-01"}]}
    second = {"visits": [{"visit_date": "2024-01-01"}], "age": 60}

    assert canonicalize_snapshot(first) == canonicalize_snapshot(second)
    assert compute_input_snapshot_sha256(first) == compute_input_snapshot_sha256(second)


def test_snapshot_hash_preserves_visit_order():
    first = {"visits": [{"visit_date": "2024-01-01"}, {"visit_date": "2024-02-01"}]}
    second = {"visits": [{"visit_date": "2024-02-01"}, {"visit_date": "2024-01-01"}]}

    assert compute_input_snapshot_sha256(first) != compute_input_snapshot_sha256(second)


def test_snapshot_hash_ignores_embedded_hash_declaration():
    snapshot = {"age": 60, "hash_algorithm": "sha256", "input_snapshot_sha256": "old"}
    equivalent = {"age": 60, "hash_algorithm": "sha256", "input_snapshot_sha256": "new"}

    assert compute_input_snapshot_sha256(snapshot) == compute_input_snapshot_sha256(equivalent)


def test_generation_fingerprint_detects_saved_content_change():
    snapshot = {"age": 60, "visits": []}
    prediction = {"risk": {"score": 0.4}}
    snapshot_hash = compute_input_snapshot_sha256(snapshot)
    fingerprint = create_generation_fingerprint(snapshot, prediction, "原始正文")

    result = verify_report_integrity(
        snapshot,
        snapshot_hash,
        fingerprint,
        prediction,
        "被修改正文",
    )

    assert result.status == "invalid"
    assert result.generation_fingerprint_valid is False


def test_legacy_report_without_integrity_fields_is_readable_but_unverifiable():
    result = verify_report_integrity(
        {"age": 60},
        None,
        None,
        {"risk": {}},
        "历史正文",
    )

    assert result.status == "unverifiable"
    assert result.input_snapshot_valid is None
    assert result.generation_fingerprint_valid is None


def test_existing_fingerprint_without_evidence_key_remains_valid():
    snapshot = {"age": 60, "visits": []}
    prediction = {"risk": {"score": 0.4}}
    content = "历史正文"
    legacy_payload = {
        "input_snapshot": snapshot,
        "prediction_result": prediction,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    legacy_fingerprint = hashlib.sha256(json.dumps(
        legacy_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()

    result = verify_report_integrity(
        snapshot, compute_input_snapshot_sha256(snapshot), legacy_fingerprint,
        prediction, content, None, None,
    )

    assert result.status == "valid"
