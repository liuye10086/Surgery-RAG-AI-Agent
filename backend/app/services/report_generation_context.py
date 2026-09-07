"""Capture immutable generation identities; workers never select active versions."""

from app.services.report_standard_identity import standard_rules_hash
from sqlalchemy import text
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from app.schemas.report_document import ReportGenerationContext
from app.services.longitudinal_release_set import (
    load_disease_release_set,
    load_release_set_record,
)
from app.services.longitudinal_model_registry import load_model_suite_record
from app.services.longitudinal_signal_interpreter import MINIMUM_SIGNAL_OBSERVATIONS
from app.services.operator_indicator_catalog import load_operator_indicator_catalog
from app.services.evidence_bundle import (
    EvidenceVersionToken,
    preflight_evidence_versions,
    build_evidence_bundle_once,
)
from app.services.standard_evidence import (
    StandardVersionToken,
    build_standard_evidence_pinned,
)


def _safe_record(context, registry_root):
    root = Path(registry_root).resolve()
    release_id = context.release_set_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", release_id):
        raise ValueError("release_set_id_invalid")
    path = (
        root / "release_sets" / context.disease_code / (release_id + ".json")
    ).resolve()
    if not path.is_relative_to(root):
        raise ValueError("release_set_id_invalid")
    record = load_release_set_record(context.disease_code, release_id, root)
    if (
        record.record_sha256,
        record.data_release_id,
        record.dataset_manifest_sha256,
        record.split_sha256,
    ) != (
        context.release_set_sha256,
        context.data_release_id,
        context.dataset_manifest_sha256,
        context.split_sha256,
    ):
        raise ValueError("generation_context_integrity_failed")
    return record


def load_pinned_model_suite(context, registry_root):
    return load_model_suite_record(_safe_record(context, registry_root), registry_root)


def capture_generation_context(snapshot, session_factory, registry_root):
    root = Path(registry_root).resolve()
    disease = snapshot["disease_code"]
    for attempt in range(2):
        record = load_disease_release_set(disease, root)
        load_model_suite_record(record, root, load_runtime=False)
        manifest_path = (
            root / "datasets" / record.data_release_id / "manifest.json"
        ).resolve()
        if not manifest_path.is_relative_to(root):
            raise ValueError("dataset_manifest_path_invalid")
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record.dataset_manifest_sha256:
            raise ValueError("dataset_manifest_hash_mismatch")
        manifest = json.loads(raw)
        minimum = manifest["minimum_visits"]
        if type(minimum) is not int or not 1 <= minimum <= 10:
            raise ValueError("dataset_manifest_invalid")
        catalog = load_operator_indicator_catalog(disease)
        if catalog.catalog_version != snapshot["indicator_catalog_version"]:
            raise ValueError("indicator_catalog_changed")
        with session_factory() as db:
            token = preflight_evidence_versions(db, snapshot["disease_id"], disease)
            rules_hash = standard_rules_hash(db, token.standard.version_id)
        with session_factory() as db:
            current_token = preflight_evidence_versions(
                db, snapshot["disease_id"], disease
            )
            current_rules_hash = standard_rules_hash(
                db, current_token.standard.version_id
            )
        current = load_disease_release_set(disease, root)
        if rules_hash != current_rules_hash:
            continue
        if (
            current.record_sha256,
            current.release_set_id,
            current_token,
            load_operator_indicator_catalog(disease).catalog_version,
        ) != (
            record.record_sha256,
            record.release_set_id,
            token,
            catalog.catalog_version,
        ):
            continue
        return ReportGenerationContext(
            disease_code=disease,
            release_set_id=record.release_set_id,
            release_set_sha256=record.record_sha256,
            data_release_id=record.data_release_id,
            dataset_manifest_sha256=record.dataset_manifest_sha256,
            split_sha256=record.split_sha256,
            indicator_catalog_sha256=catalog.catalog_version,
            indicator_labels=[
                {
                    "code": item.code,
                    "label": item.name_cn or item.name_en,
                    "allowed_units": list(item.allowed_units),
                    "context_requirements": list(item.context_requirements),
                }
                for item in catalog.items
            ],
            minimum_visits=minimum,
            minimum_signal_observations=MINIMUM_SIGNAL_OBSERVATIONS,
            evidence_token=asdict(token),
            standard_rules_sha256=rules_hash,
        )
    raise ValueError("generation_context_changed")


def build_pinned_evidence(snapshot, context, session_factory):
    values = context.evidence_token.model_dump()
    values["standard"] = StandardVersionToken(**values["standard"])
    token = EvidenceVersionToken(**values)
    with session_factory() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        if (
            standard_rules_hash(db, token.standard.version_id)
            != context.standard_rules_sha256
        ):
            raise ValueError("standard_integrity_failed")
        return build_evidence_bundle_once(
            db, snapshot, token, standard_builder=build_standard_evidence_pinned
        )
