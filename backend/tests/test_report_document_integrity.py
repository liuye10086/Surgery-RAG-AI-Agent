import pytest
from datetime import datetime, timezone
from backend.tests.report_document_fixtures import demo_inputs, document_payload
from app.services.report_document_builder import build_report_document
from app.services.report_publication import build_publication
from app.services.report_integrity import (
    verify_report_integrity,
    compute_input_snapshot_sha256,
)


def published():
    snapshot, context, audited, evidence = demo_inputs()
    document = build_report_document(
        17,
        datetime(2026, 9, 7, tzinfo=timezone.utc),
        snapshot,
        context,
        audited.prediction,
        audited.model_runs,
        evidence,
    )
    return snapshot, build_publication(snapshot, audited.prediction, evidence, document)


def test_v2_roundtrip_and_document_tamper():
    snapshot, pub = published()
    kwargs = dict(
        input_snapshot=snapshot,
        input_snapshot_sha256=compute_input_snapshot_sha256(snapshot),
        generation_fingerprint=pub.generation_fingerprint,
        prediction_result=pub.prediction_result,
        content=pub.content,
        evidence_snapshot=pub.evidence_snapshot,
        evidence_sha256=pub.evidence_snapshot_sha256,
        report_document=pub.report_document.model_dump(mode="json"),
        report_document_sha256=pub.report_document_sha256,
        generation_fingerprint_version="v2",
    )
    assert verify_report_integrity(**kwargs).status == "valid"
    kwargs["report_document"]["identity"]["age"] = 63
    assert verify_report_integrity(**kwargs).status == "invalid"


@pytest.mark.parametrize("bad_prediction", [{"score": float("nan")}, {"evidence": []}])
def test_malformed_stored_prediction_is_invalid_not_an_exception(bad_prediction):
    snapshot, pub = published()
    assert (
        verify_report_integrity(
            snapshot,
            compute_input_snapshot_sha256(snapshot),
            pub.generation_fingerprint,
            bad_prediction,
            pub.content,
            pub.evidence_snapshot,
            pub.evidence_snapshot_sha256,
            saved_sources=pub.sources,
            report_document=pub.report_document.model_dump(mode="json"),
            report_document_sha256=pub.report_document_sha256,
            generation_fingerprint_version="v2",
        ).status
        == "invalid"
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda d: setattr(d.model_runs[0].runtime, "reason_code", "different_runtime"),
        lambda d: setattr(
            d.identity, "anchor_date", __import__("datetime").date(2025, 9, 6)
        ),
        lambda d: d.sections[0].paragraphs.clear(),
        lambda d: setattr(d.summary, "invoked_model_count", 0),
        lambda d: setattr(d.sections[0], "title", "假的标题"),
        lambda d: setattr(
            d.identity, "batch_id", "33333333-3333-4333-8333-333333333333"
        ),
    ],
)
def test_publication_rejects_incomplete_or_inconsistent_document(change):
    snapshot, pub = published()
    from app.services.evidence_bundle import EvidenceBuildResult
    from app.schemas.longitudinal_evidence import EvidenceBundle

    evidence = EvidenceBuildResult(
        EvidenceBundle.model_validate(pub.evidence_snapshot),
        "complete",
        tuple(pub.sources),
    )
    change(pub.report_document)
    with pytest.raises(ValueError):
        build_publication(
            snapshot, pub.prediction_result, evidence, pub.report_document
        )


@pytest.mark.parametrize("version", ["v2", "unknown", None])
def test_partial_new_fields_cannot_downgrade_to_legacy(version):
    assert (
        verify_report_integrity(
            {},
            None,
            None,
            {},
            "",
            report_document=document_payload(),
            generation_fingerprint_version=version,
        ).status
        == "invalid"
    )
