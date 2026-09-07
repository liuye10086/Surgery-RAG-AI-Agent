import pytest
from app.services.report_generation_context import load_pinned_model_suite
from app.schemas.report_document import ReportGenerationContext
from backend.tests.report_document_fixtures import context_payload


@pytest.mark.parametrize(
    "release_id", ["../escape", "/absolute", "C:\\outside", "a/b", ".."]
)
def test_pinned_loader_rejects_unsafe_path_before_read(tmp_path, release_id):
    context = ReportGenerationContext.model_validate(
        {**context_payload(), "release_set_id": release_id}
    )
    with pytest.raises(ValueError, match="release_set_id_invalid"):
        load_pinned_model_suite(context, tmp_path)


def test_pinned_loader_ignores_active_changes_and_rejects_changed_record(
    monkeypatch, tmp_path
):
    from backend.tests.report_generation_fixtures import pinned_suite_fixture
    from app.services import longitudinal_model_registry as registry

    context, root = pinned_suite_fixture(tmp_path)
    monkeypatch.setattr(
        registry,
        "load_disease_release_set",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("active read")),
    )
    (root / "active" / "fatty_liver.json").write_text("{}")
    suite = load_pinned_model_suite(context, root)
    assert suite.release_set_id == context.release_set_id
    record = root / "release_sets" / "fatty_liver" / (context.release_set_id + ".json")
    record.write_bytes(record.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="generation_context_integrity_failed"):
        load_pinned_model_suite(context, root)


def test_metadata_capture_does_not_deserialize_models(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from unittest.mock import Mock
    from backend.tests.report_generation_fixtures import pinned_suite_fixture
    from app.services import report_generation_context as service
    from app.services import longitudinal_model_registry as registry
    from app.services.evidence_bundle import EvidenceVersionToken
    from app.services.standard_evidence import StandardVersionToken
    from backend.tests.report_document_fixtures import snapshot_payload

    context, root = pinned_suite_fixture(tmp_path)
    values = context.evidence_token.model_dump()
    values["standard"] = StandardVersionToken(**values["standard"])
    token = EvidenceVersionToken(**values)
    monkeypatch.setattr(service, "preflight_evidence_versions", lambda *a: token)
    monkeypatch.setattr(
        service, "standard_rules_hash", lambda *a: context.standard_rules_sha256
    )
    monkeypatch.setattr(
        registry.joblib,
        "load",
        lambda *a: (_ for _ in ()).throw(
            AssertionError("deserialized during admission")
        ),
    )

    @contextmanager
    def factory():
        yield Mock()

    snapshot = snapshot_payload()
    snapshot["indicator_catalog_version"] = context.indicator_catalog_sha256
    captured = service.capture_generation_context(snapshot, factory, root)
    assert captured.release_set_sha256 == context.release_set_sha256
    snapshot["indicator_catalog_version"] = "0" * 64
    with pytest.raises(ValueError, match="indicator_catalog_changed"):
        service.capture_generation_context(snapshot, factory, root)


def test_pinned_standard_retains_approved_old_version_but_rejects_revocation(
    monkeypatch, tmp_path
):
    import hashlib
    from types import SimpleNamespace as NS
    from unittest.mock import Mock
    from app.services import standard_evidence as service

    document = tmp_path / "standard.txt"
    document.write_bytes(b"approved test source")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    version = NS(
        status="approved",
        standard_id=1,
        content_hash=digest,
        rules=[],
        standard_document=NS(id=3, content_hash=digest, file_path=str(document)),
        standard=NS(
            disease_id=1, disease=NS(code="fatty_liver"), current_version=NS(id=999)
        ),
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = version
    monkeypatch.setattr(
        service, "_build_standard_evidence_in_transaction", lambda *a: "pinned A"
    )
    token = service.StandardVersionToken(1, 2, 3, digest, digest)
    snapshot = {"disease_id": 1, "disease_code": "fatty_liver"}
    assert service.build_standard_evidence_pinned(db, token, snapshot) == "pinned A"
    version.status = "retired"
    with pytest.raises(service.StandardEvidenceError, match="standard_not_approved"):
        service.build_standard_evidence_pinned(db, token, snapshot)
