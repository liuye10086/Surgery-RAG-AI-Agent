import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.standard_draft_service import DraftPreparationSpec, plan_draft_preparation, prepare_standard_drafts


from docx import Document


FATTY_BYTES = b"fatty-source"
FATTY_SHA256 = hashlib.sha256(FATTY_BYTES).hexdigest()
BOTH_SPECS = []


def _spec(tmp_path, dataset, content, sha, label):
    source = tmp_path / f"{dataset}.docx"
    document = Document()
    document.add_paragraph(content.decode("utf-8"))
    document.save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    return DraftPreparationSpec(
        dataset=dataset,
        disease_name="脂肪肝" if dataset == "fatty_liver" else "阿尔茨海默病",
        source_path=source,
        source_sha256=sha,
        version_label=label,
        parser_version="v2",
    )


class DraftSession:
    def __init__(self, fail_on_dataset=None, version_status="draft", diseases=None):
        self.fail_on_dataset = fail_on_dataset
        self.version_status = version_status
        self.diseases = list(diseases or [])
        self.commits = 0
        self.rollbacks = 0
        self.created_versions = []
        self.added = []

    def query(self, model):
        session = self
        name = model.__name__

        class Query:
            def __init__(self):
                self.filters = ()

            def filter(self, *args, **kwargs):
                self.filters = args
                return self
            def with_for_update(self): return self
            def first(self):
                if name == "Disease" and session.diseases:
                    return session.diseases.pop(0)
                return None
            def all(self): return []

        return Query()

    def add(self, value):
        self.added.append(value)
        name = value.__class__.__name__
        if name == "StandardDocument":
            value.id = 10
        elif name == "ReferenceStandard":
            value.id = 20
        elif name == "ReferenceStandardVersion":
            value.id = len(self.created_versions) + 1
            self.created_versions.append(value)

    def flush(self):
        return None

    def commit(self): self.commits += 1

    def rollback(self): self.rollbacks += 1


def test_draft_plan_matches_documents_by_hash_not_filename(tmp_path):
    spec = _spec(tmp_path, "fatty_liver", FATTY_BYTES, FATTY_SHA256, "fatty-v1")
    plan = plan_draft_preparation(DraftSession(), [spec])
    assert plan.items[0].source_hash_matches is True


def test_prepare_two_drafts_does_not_commit_or_own_the_outer_rollback(tmp_path, monkeypatch):
    fatty = _spec(tmp_path, "fatty_liver", FATTY_BYTES, FATTY_SHA256, "fatty-v1")
    ad = _spec(tmp_path, "ad", b"ad-source", hashlib.sha256(b"ad-source").hexdigest(), "ad-v1")
    db = DraftSession(
        fail_on_dataset="ad",
        diseases=[SimpleNamespace(id=2, name="脂肪肝"), SimpleNamespace(id=4, name="阿尔茨海默病")],
    )
    def fail_on_ad(path, *, parser_version):
        if path.stem == "ad":
            raise RuntimeError("ad parse failed")
        return SimpleNamespace(segments=[], rule_candidates=[])
    monkeypatch.setattr("app.services.standard_draft_service.parse_standard_docx", fail_on_ad)
    with pytest.raises(RuntimeError):
        prepare_standard_drafts(db, [fatty, ad], admin_id=7)
    assert db.commits == 0
    assert db.rollbacks == 0


def test_parse_draft_replaces_only_unapproved_parse_artifacts(tmp_path):
    fatty = _spec(tmp_path, "fatty_liver", FATTY_BYTES, FATTY_SHA256, "fatty-v1")
    db = DraftSession(version_status="draft", diseases=[SimpleNamespace(id=2, name="脂肪肝")])
    from app.services.standard_parser import NumericExpression, RuleCandidate, Segment
    import app.services.standard_draft_service as service
    segment = Segment(raw_text="ALT 7-40 U/L", segment_type="table_row", table_index=0, row_index=0)
    candidate = RuleCandidate(raw_text=segment.raw_text, segment=segment, indicator_name="ALT", numeric=NumericExpression(lower=7, upper=40, unit="U/L"), rule_type="numeric_range", machine_actionability="calculable")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "parse_standard_docx", lambda *args, **kwargs: SimpleNamespace(segments=[segment], rule_candidates=[candidate]))
    result = prepare_standard_drafts(db, [fatty], admin_id=7)
    monkeypatch.undo()
    assert result.items[0].segment_count > 0
    assert result.items[0].candidate_count > 0
    assert all(version.status == "draft" for version in db.created_versions)


def test_prepare_draft_uses_database_disease_identity_instead_of_dataset_position(tmp_path, monkeypatch):
    fatty = _spec(tmp_path, "fatty_liver", FATTY_BYTES, FATTY_SHA256, "fatty-v1")
    db = DraftSession(diseases=[SimpleNamespace(id=27, name="脂肪肝")])
    monkeypatch.setattr(
        "app.services.standard_draft_service.parse_standard_docx",
        lambda *args, **kwargs: SimpleNamespace(segments=[], rule_candidates=[]),
    )

    prepare_standard_drafts(db, [fatty], admin_id=7)

    assert db.created_versions[0].standard_id == 20
    standard = next(item for item in db.added if item.__class__.__name__ == "ReferenceStandard")
    assert standard.disease_id == 27


def test_prepare_draft_rejects_missing_database_disease(tmp_path):
    fatty = _spec(tmp_path, "fatty_liver", FATTY_BYTES, FATTY_SHA256, "fatty-v1")

    with pytest.raises(ValueError, match="数据库中缺少疾病"):
        prepare_standard_drafts(DraftSession(), [fatty], admin_id=7)
