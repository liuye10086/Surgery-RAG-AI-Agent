from app.db.models import (
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
    assert {"status", "document_id", "supersedes_version_id"}.issubset(
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


def test_reference_range_projection_defaults_to_non_current():
    column = ReferenceRange.__table__.columns["is_current_projection"]
    assert column.server_default is not None
    assert column.server_default.arg in {"false", "0"}
