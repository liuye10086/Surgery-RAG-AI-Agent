from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from test_synthetic_numeric_prediction import literal_input


def publication_fixture(disease="ad", unavailable=False):
    from app.services.synthetic_numeric_prediction import predict_synthetic_numeric, numeric_input_sha256
    from app.services.synthetic_case_source import numeric_display_visits
    from app.services.longitudinal_case_service import build_input_snapshot
    from app.services.report_integrity import compute_input_snapshot_sha256

    raw = literal_input(disease)
    if unavailable:
        for packet in raw["packets"]:
            packet.update(input_status="unavailable", input_reason="population_not_confirmed")
    visits = numeric_display_visits(raw)
    case = SimpleNamespace(id=1, disease_id=2, user_id=3,
        disease=SimpleNamespace(code=disease, name="AD" if disease == "ad" else "脂肪肝"),
        anonymous_case_code="CASE-ABCD-EFGH", age=65, sex="female",
        baseline_stage="mci" if disease == "ad" else "pre_cirrhosis", notes=None)
    snapshot = build_input_snapshot(case, visits, {})
    snapshot.update(schema_version="synthetic_numeric_report_input.v1", report_kind="synthetic_numeric",
        user_id=3, generation_batch_id="11111111-1111-4111-8111-111111111111",
        numeric_input=raw, engineering_source_sha256="c" * 64)
    snapshot["input_snapshot_sha256"] = compute_input_snapshot_sha256(snapshot)
    result = predict_synthetic_numeric(raw)
    context = {"schema_version": "synthetic_numeric_generation_context.v1", "disease_code": disease,
        "numeric_input_sha256": numeric_input_sha256(raw), "engineering_source_sha256": "c" * 64,
        "algorithm": result.algorithm.model_dump(mode="json"),
        "template_version": "synthetic_numeric_report.zh-CN.v1"}
    return snapshot, context, result


def build_fixture(disease="ad", unavailable=False):
    from app.services.synthetic_report_publication import build_synthetic_document, build_synthetic_publication
    snapshot, context, result = publication_fixture(disease, unavailable)
    document = build_synthetic_document(7, datetime(2026, 9, 14, tzinfo=timezone.utc), snapshot, context, result)
    return snapshot, build_synthetic_publication(snapshot, result, document)


def test_snapshot_validation_does_not_require_prediction(monkeypatch):
    from app.services import synthetic_report_publication as publication
    snapshot, context, _ = publication_fixture()
    monkeypatch.setattr(publication, "_validate_saved_prediction", lambda *args: pytest.fail("prediction validation invoked"))
    saved_context, numeric = publication.validate_synthetic_snapshot(snapshot, context)
    assert saved_context.model_dump(mode="json") == context
    assert numeric.model_dump(mode="json") == snapshot["numeric_input"]


@pytest.mark.parametrize("part", ["numeric_hash", "source", "display"])
def test_snapshot_validation_rejects_changed_binding_without_prediction(part):
    from app.services.synthetic_report_publication import validate_synthetic_snapshot
    from app.services.report_integrity import compute_input_snapshot_sha256
    snapshot, context, _ = publication_fixture()
    if part == "numeric_hash":
        context["numeric_input_sha256"] = "d" * 64
    elif part == "source":
        context["engineering_source_sha256"] = "d" * 64
    else:
        snapshot["visits"][0]["indicators"][0]["value"] = 21.0
        snapshot["input_snapshot_sha256"] = compute_input_snapshot_sha256(snapshot)
    with pytest.raises(ValueError):
        validate_synthetic_snapshot(snapshot, context)


@pytest.mark.parametrize("disease,unit,value", [("ad", "分", 22.0), ("fatty_liver", "U/L", 47.5)])
def test_strict_publication_preserves_numeric_facts_and_engineering_disclosure(disease, unit, value):
    from app.schemas.report_document import parse_report_document, parse_publication, Publication
    snapshot, publication = build_fixture(disease)
    assert publication.generation_fingerprint_version == "v3"
    assert set(type(publication).model_fields) == set(Publication.model_fields)
    assert publication.sources == []
    assert (publication.evidence_status, publication.standard_evidence_status, publication.reference_case_status) == ("not_requested",) * 3
    assert publication.evidence_snapshot["source_kind"] == "synthetic"
    assert publication.evidence_snapshot["clinical_validity_claim"] is False
    assert publication.evidence_snapshot["production_enabled"] is False
    assert [(p["horizon_months"], p["target_date"], p["value"], p["unit"]) for p in publication.prediction_result["predictions"]] == [
        (6, "2024-02-29", value, unit), (12, "2024-08-31", value, unit)]
    assert publication.report_document.numeric_input.model_dump(mode="json") == snapshot["numeric_input"]
    assert "合成数据" in publication.content and "末次值保持" in publication.content
    assert "2023-01-01" in publication.content and "2024-02-29" in publication.content
    assert "尚无临床有效性结论" in publication.content
    assert parse_report_document(publication.report_document.model_dump(mode="json")) == publication.report_document
    assert parse_publication(publication.model_dump(mode="json")) == publication


def test_unavailable_values_keep_reason_in_saved_document_and_content():
    _, publication = build_fixture(unavailable=True)
    assert all(p.value is None and p.reason == "population_not_confirmed" for p in publication.report_document.prediction.predictions)
    assert "人群条件尚未确认" in publication.content


@pytest.mark.parametrize("part", ["batch", "age", "stage", "disease", "input", "context", "prediction", "display_value", "display_unit", "display_date", "display_method"])
def test_publication_rejects_correlated_fact_tampering(part):
    from app.services.synthetic_report_publication import build_synthetic_publication
    from app.services.report_integrity import compute_input_snapshot_sha256
    snapshot, publication = build_fixture()
    document = publication.report_document.model_dump(mode="json")
    result = deepcopy(publication.prediction_result)
    if part == "batch": snapshot["generation_batch_id"] = "22222222-2222-4222-8222-222222222222"
    elif part == "age": snapshot["age"] = 64
    elif part == "stage": snapshot["baseline_stage"] = "dementia"
    elif part == "disease": snapshot["disease_code"] = "fatty_liver"
    elif part == "input": document["numeric_input"]["packets"][0]["input_observations"][0]["value"] = 21.0
    elif part == "context": document["generation_context"]["engineering_source_sha256"] = "d" * 64
    elif part == "prediction": result["predictions"][0]["value"] = 21.0
    elif part == "display_value": snapshot["visits"][0]["indicators"][0]["value"] = 21.0
    elif part == "display_unit": snapshot["visits"][0]["indicators"][0]["unit"] = "U/L"
    elif part == "display_date": snapshot["visits"][0]["visit_date"] = "2023-01-03"
    elif part == "display_method": snapshot["visits"][0]["visit_context"]["method"] = "other"
    snapshot["input_snapshot_sha256"] = compute_input_snapshot_sha256(snapshot)
    with pytest.raises(ValueError):
        build_synthetic_publication(snapshot, result, document)


@pytest.mark.parametrize("field", ["content", "prediction", "evidence", "document", "sources", "snapshot"])
def test_history_integrity_rebuild_rejects_tampering(field, monkeypatch):
    from app.services.synthetic_report_publication import verify_synthetic_integrity
    from app.services import synthetic_numeric_prediction as numeric
    snapshot, publication = build_fixture()
    monkeypatch.setattr(numeric, "numeric_algorithm_identity", lambda: pytest.fail("historical read loaded active algorithm"))
    args = dict(snapshot=snapshot, snapshot_sha256=snapshot["input_snapshot_sha256"],
        fingerprint=publication.generation_fingerprint, prediction=publication.prediction_result,
        content=publication.content, evidence=publication.evidence_snapshot,
        evidence_sha256=publication.evidence_snapshot_sha256,
        document=publication.report_document.model_dump(mode="json"),
        document_sha256=publication.report_document_sha256, saved_sources=[])
    assert verify_synthetic_integrity(**args)
    if field == "content": args["content"] += "诊断结论"
    elif field == "prediction": args["prediction"]["predictions"][0]["value"] = 21.0
    elif field == "evidence": args["evidence"]["clinical_validity_claim"] = True
    elif field == "document": args["document"]["identity"]["age"] = 64
    elif field == "sources": args["saved_sources"] = [{"source": "invented"}]
    elif field == "snapshot": args["snapshot"]["age"] = 64
    assert not verify_synthetic_integrity(**args)


def test_unknown_schema_and_extra_fields_are_rejected():
    from app.schemas.report_document import parse_report_document, parse_publication
    _, publication = build_fixture()
    document = publication.report_document.model_dump(mode="json")
    document["schema_version"] = "synthetic_numeric_report_document.v999"
    with pytest.raises(ValueError): parse_report_document(document)
    raw = publication.model_dump(mode="json")
    raw["generation_fingerprint_version"] = "v999"
    with pytest.raises(ValueError): parse_publication(raw)
    raw = publication.model_dump(mode="json")
    raw["diagnosis"] = "unexpected"
    with pytest.raises(ValueError): parse_publication(raw)


@pytest.mark.parametrize("field", ["clinical_validity_claim", "production_enabled"])
def test_evidence_disclosures_require_explicit_boolean_false(field):
    from app.schemas.report_document import parse_publication
    _, publication = build_fixture()
    raw = publication.model_dump(mode="json")
    raw["evidence_snapshot"][field] = 0
    with pytest.raises(ValueError):
        parse_publication(raw)


def test_fresh_history_verification_does_not_import_or_read_algorithm_sources(tmp_path):
    import json
    import subprocess
    import sys

    snapshot, publication = build_fixture()
    payload = tmp_path / "publication.json"
    payload.write_text(json.dumps({"snapshot": snapshot, "publication": publication.model_dump(mode="json")}), encoding="utf-8")
    script = '''
import importlib.abc
import json
from pathlib import Path
import sys
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
class DenyAlgorithm(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"app.services.synthetic_numeric_prediction", "app.services.prediction_calculation"}:
            raise AssertionError("historical verification imported algorithm")
sys.meta_path.insert(0, DenyAlgorithm())
original_read = Path.read_bytes
def protected_read(path):
    if path.name in {"synthetic_numeric_prediction.py", "prediction_calculation.py"}:
        raise AssertionError("historical verification read algorithm source")
    return original_read(path)
Path.read_bytes = protected_read
from app.services.synthetic_report_publication import verify_synthetic_integrity
p, s = data["publication"], data["snapshot"]
assert verify_synthetic_integrity(s, s["input_snapshot_sha256"], p["generation_fingerprint"],
    p["prediction_result"], p["content"], p["evidence_snapshot"], p["evidence_snapshot_sha256"],
    p["report_document"], p["report_document_sha256"], p["sources"])
'''
    result = subprocess.run([sys.executable, "-c", script, str(payload)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
