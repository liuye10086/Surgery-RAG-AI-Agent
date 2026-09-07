"""Fail-closed construction of the one atomic report publication payload."""

from datetime import date
from app.schemas.longitudinal_model_registry import ModelRuntimeStatus
import hashlib
import json

from app.schemas.report_document import Publication, ReportDocument
from app.schemas.longitudinal_evidence import EvidenceBundle
from app.services.evidence_bundle import (
    verify_evidence_bundle,
    build_sources_projection,
)
from app.services.longitudinal_prediction import prediction_result_to_dict
from app.services.report_document_renderer import render_report_document
from app.services.report_display_labels import SECTION_TITLES
from app.services.report_integrity import create_generation_fingerprint


def hash_report_document(document):
    return hashlib.sha256(
        json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def fingerprint_v2(snapshot, prediction, content, evidence, document_sha256):
    body = {
        "version": "v2",
        "legacy_payload_sha256": create_generation_fingerprint(
            snapshot, prediction, content, evidence
        ),
        "report_document_sha256": document_sha256,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_publication(snapshot, prediction, evidence, document):
    prediction = prediction_result_to_dict(prediction)
    bundle = EvidenceBundle.model_validate(evidence.bundle.model_dump(mode="json"))
    document = ReportDocument.model_validate(document.model_dump(mode="json"))
    identity, context = document.identity, document.generation_context
    sources = build_sources_projection(bundle)
    runs = document.model_runs
    runtime_statuses = [
        prediction["model_status"]["outcome"],
        prediction["model_status"]["stage"],
        *[t["model_status"] for t in prediction.get("trend_predictions", [])],
    ]
    expected_runs = {
        status["task"]: ModelRuntimeStatus.model_validate(status).model_dump(
            mode="json"
        )
        for status in runtime_statuses
        if status.get("task")
    }
    checks = [
        verify_evidence_bundle(bundle),
        identity.anchor_date
        == max(date.fromisoformat(str(v["visit_date"])) for v in snapshot["visits"]),
        identity.horizon_days == 365,
        {r.task: r.runtime.model_dump(mode="json") for r in runs} == expected_runs,
        all(
            r.runtime.status != "available" or r.input_audit.model_invoked for r in runs
        ),
        str(identity.batch_id)
        == str(bundle.generation_batch_id)
        == snapshot.get("generation_batch_id"),
        identity.disease_code
        == bundle.disease_code
        == snapshot.get("disease_code")
        == prediction["disease"]["dataset"],
        identity.age == snapshot.get("age"),
        identity.sex == snapshot.get("sex"),
        identity.baseline_stage == snapshot.get("baseline_stage"),
        identity.anonymous_case_code == snapshot.get("anonymous_case_code"),
        document.evidence.evidence_bundle_id == bundle.evidence_bundle_id,
        document.evidence.evidence_snapshot_sha256
        == bundle.integrity.evidence_snapshot_sha256,
        context.indicator_catalog_sha256 == snapshot.get("indicator_catalog_version"),
        context.evidence_token.standard.version_id
        == bundle.standard.version.version_id,
        context.evidence_token.standard.document_id
        == bundle.standard.document.document_id,
        context.evidence_token.standard.document_sha256
        == bundle.standard.document.content_sha256,
        context.evidence_token.standard.version_sha256
        == bundle.standard.version.content_sha256,
        context.evidence_token.dataset_release_id
        == bundle.reference_cases.data_release.dataset_release_id,
        context.evidence_token.data_content_sha256
        == bundle.reference_cases.data_release.data_content_sha256,
        context.evidence_token.similarity_config_hash
        == bundle.reference_cases.configuration_hash,
        context.evidence_token.logical_dataset
        in (None, bundle.reference_cases.data_release.logical_dataset),
        sources == prediction.get("evidence", {}).get("sources"),
        [s.title for s in document.sections] == SECTION_TITLES,
        all(s.paragraphs or any(t.rows for t in s.tables) for s in document.sections),
        len({r.task for r in runs}) == len(runs),
        all(r.task == r.runtime.task == r.input_audit.task for r in runs),
        document.summary.selected_model_count == len(runs),
        document.summary.invoked_model_count
        == sum(r.input_audit.model_invoked for r in runs),
        document.summary.available_model_count
        == sum(r.runtime.status == "available" for r in runs),
        document.summary.evidence_status == evidence.evidence_status,
    ]
    release = prediction.get("release_set") or {}
    checks.extend(
        release.get(k) == v
        for k, v in {
            "release_set_id": context.release_set_id,
            "release_set_sha256": context.release_set_sha256,
            "data_release_id": context.data_release_id,
            "split_sha256": context.split_sha256,
        }.items()
    )
    if not all(checks):
        raise ValueError("report_generation_contract_mismatch")
    content = render_report_document(document)
    digest = hash_report_document(document)
    saved_evidence = bundle.model_dump(mode="json")
    return Publication(
        content=content,
        prediction_result=prediction,
        sources=sources,
        evidence_snapshot=saved_evidence,
        evidence_snapshot_sha256=bundle.integrity.evidence_snapshot_sha256,
        evidence_status=evidence.evidence_status,
        standard_evidence_status=bundle.standard.status,
        reference_case_status=bundle.reference_cases.status,
        report_document=document,
        report_document_sha256=digest,
        generation_fingerprint=fingerprint_v2(
            snapshot, prediction, content, saved_evidence, digest
        ),
    )
