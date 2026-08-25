from app.db.models import (
    Disease,
    ReferenceRange,
    ReferenceStandard,
    ReferenceStandardVersion,
    StandardChangeLog,
    StandardIndicator,
    StandardParseCandidate,
    StandardRule,
    StandardRuleCondition,
    StandardSegment,
)


def test_standard_entities_and_projection_columns_exist():
    assert ReferenceStandard.__table__.columns["disease_id"].unique
    assert ReferenceStandardVersion.__table__.columns["content_hash"].nullable is False
    assert {"status", "standard_document_id", "supersedes_version_id"}.issubset(
        ReferenceStandardVersion.__table__.columns.keys()
    )
    assert {"source_segment_id", "machine_actionability", "target_state_type"}.issubset(
        StandardRule.__table__.columns.keys()
    )
    assert {"standard_id", "standard_version_id", "standard_rule_id", "is_current_projection"}.issubset(
        ReferenceRange.__table__.columns.keys()
    )
    assert {"version_id", "raw_text", "segment_type"}.issubset(StandardSegment.__table__.columns.keys())
    assert {"segment_id", "source_type", "candidate_json"}.issubset(StandardParseCandidate.__table__.columns.keys())
    assert {"rule_id", "node_type", "payload"}.issubset(StandardRuleCondition.__table__.columns.keys())
    assert {"entity_type", "before_json", "after_json", "reason"}.issubset(StandardChangeLog.__table__.columns.keys())


def test_standard_document_model_and_one_to_one_version_link():
    from app.db.models import StandardDocument

    columns = StandardDocument.__table__.columns
    assert {
        "id", "title", "filename", "file_path", "file_type", "file_size",
        "content_hash", "uploaded_by", "created_at",
    }.issubset(columns.keys())
    assert columns["content_hash"].nullable is False
    assert "document_id" not in ReferenceStandardVersion.__table__.columns
    assert ReferenceStandardVersion.__table__.columns["standard_document_id"].nullable is False
    assert any(
        constraint.name == "uq_reference_standard_versions_standard_document"
        for constraint in ReferenceStandardVersion.__table__.constraints
    )


def test_reference_range_projection_defaults_to_non_current():
    column = ReferenceRange.__table__.columns["is_current_projection"]
    assert column.server_default is not None
    assert column.server_default.arg in {"false", "0"}


def test_reference_standard_restricts_disease_deletion_at_database_boundary():
    disease_id = ReferenceStandard.__table__.columns["disease_id"]
    foreign_key = next(iter(disease_id.foreign_keys))

    assert foreign_key.constraint.name == "reference_standards_disease_id_fkey"
    assert foreign_key.ondelete == "RESTRICT"

    relationship = Disease.reference_standards.property
    assert relationship.passive_deletes is True
    assert "delete" not in relationship.cascade
