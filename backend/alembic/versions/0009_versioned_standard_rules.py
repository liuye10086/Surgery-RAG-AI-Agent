"""add versioned reference standard rules layer"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reference_standards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("disease_id", sa.Integer(), sa.ForeignKey("diseases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("disease_id", name="uq_reference_standards_disease"),
    )

    op.create_table(
        "reference_standard_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("standard_id", sa.Integer(), sa.ForeignKey("reference_standards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("supersedes_version_id", sa.Integer(), sa.ForeignKey("reference_standard_versions.id", ondelete="SET NULL")),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft', 'review', 'approved', 'retired')", name="ck_reference_standard_versions_status"),
    )
    op.create_foreign_key(
        "fk_reference_standards_current_version",
        "reference_standards",
        "reference_standard_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_reference_standard_versions_standard_status", "reference_standard_versions", ["standard_id", "status"])

    op.create_table(
        "standard_indicators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_key", sa.String(length=200), nullable=False),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.Column("name_cn", sa.String(length=200)),
        sa.Column("aliases", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("domain", sa.String(length=100)),
        sa.Column("specimen_or_modality", sa.String(length=100)),
        sa.Column("data_type", sa.String(length=50), nullable=False, server_default="qualitative"),
        sa.Column("scale_or_method", sa.String(length=200)),
        sa.Column("default_unit", sa.String(length=50)),
        sa.Column("clinical_dimension", sa.String(length=100)),
        sa.Column("allows_numeric_comparison", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("canonical_key", name="uq_standard_indicators_canonical_key"),
    )

    op.create_table(
        "standard_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_title", sa.String(length=300)),
        sa.Column("paragraph_index", sa.Integer()),
        sa.Column("table_index", sa.Integer()),
        sa.Column("row_index", sa.Integer()),
        sa.Column("column_index", sa.Integer()),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("segment_type", sa.String(length=50), nullable=False),
        sa.Column("parse_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("review_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("source_metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_standard_segments_version_location", "standard_segments", ["version_id", "table_index", "row_index"])

    op.create_table(
        "standard_parse_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("standard_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100)),
        sa.Column("prompt_version", sa.String(length=100)),
        sa.Column("raw_output", sa.Text()),
        sa.Column("candidate_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_standard_parse_candidates_segment", "standard_parse_candidates", ["segment_id"])

    op.create_table(
        "standard_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("indicator_id", sa.Integer(), sa.ForeignKey("standard_indicators.id", ondelete="SET NULL")),
        sa.Column("source_segment_id", sa.Integer(), sa.ForeignKey("standard_segments.id", ondelete="SET NULL")),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("comparator", sa.String(length=5)),
        sa.Column("lower", sa.Float()),
        sa.Column("upper", sa.Float()),
        sa.Column("lower_inclusive", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("upper_inclusive", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("sex", sa.String(length=10)),
        sa.Column("category", sa.String(length=100)),
        sa.Column("applicability", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("target_state_type", sa.String(length=50), nullable=False),
        sa.Column("target_state_value", sa.String(length=200)),
        sa.Column("clinical_dimension", sa.String(length=100)),
        sa.Column("evidence_type", sa.String(length=100)),
        sa.Column("machine_actionability", sa.String(length=50), nullable=False, server_default="evidence-only"),
        sa.Column("interpretation", sa.Text()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_group", sa.String(length=100)),
        sa.Column("framework", sa.String(length=100)),
        sa.Column("biomarker_axis", sa.String(length=10)),
        sa.Column("biomarker_state", sa.String(length=100)),
        sa.Column("stage", sa.String(length=100)),
        sa.Column("clinical_function", sa.Text()),
        sa.Column("conditions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_standard_rules_version_indicator", "standard_rules", ["version_id", "indicator_id"])
    op.create_index("ix_standard_rules_conflict_group", "standard_rules", ["version_id", "conflict_group"])

    op.create_table(
        "standard_rule_conditions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("standard_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("standard_rule_conditions.id", ondelete="CASCADE")),
        sa.Column("node_type", sa.String(length=50), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_standard_rule_conditions_rule_parent", "standard_rule_conditions", ["rule_id", "parent_id"])

    op.create_table(
        "standard_change_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("before_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("after_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_standard_change_logs_entity", "standard_change_logs", ["entity_type", "entity_id"])

    for name, column in [
        ("standard_id", sa.Column("standard_id", sa.Integer(), sa.ForeignKey("reference_standards.id", ondelete="SET NULL"))),
        ("standard_version_id", sa.Column("standard_version_id", sa.Integer(), sa.ForeignKey("reference_standard_versions.id", ondelete="SET NULL"))),
        ("standard_rule_id", sa.Column("standard_rule_id", sa.Integer(), sa.ForeignKey("standard_rules.id", ondelete="SET NULL"))),
        ("applicability_hash", sa.Column("applicability_hash", sa.String(length=64))),
        ("is_current_projection", sa.Column("is_current_projection", sa.Boolean(), nullable=False, server_default="false")),
    ]:
        op.add_column("reference_ranges", column)
    op.create_index(
        "uq_reference_ranges_current_projection",
        "reference_ranges",
        ["standard_id", "indicator_name", "sex", "category", "applicability_hash"],
        unique=True,
        postgresql_where=sa.text("is_current_projection IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_reference_ranges_current_projection", table_name="reference_ranges")
    for name in ["is_current_projection", "applicability_hash", "standard_rule_id", "standard_version_id", "standard_id"]:
        op.drop_column("reference_ranges", name)
    op.drop_index("ix_standard_change_logs_entity", table_name="standard_change_logs")
    op.drop_table("standard_change_logs")
    op.drop_index("ix_standard_rule_conditions_rule_parent", table_name="standard_rule_conditions")
    op.drop_table("standard_rule_conditions")
    op.drop_index("ix_standard_rules_conflict_group", table_name="standard_rules")
    op.drop_index("ix_standard_rules_version_indicator", table_name="standard_rules")
    op.drop_table("standard_rules")
    op.drop_index("ix_standard_parse_candidates_segment", table_name="standard_parse_candidates")
    op.drop_table("standard_parse_candidates")
    op.drop_index("ix_standard_segments_version_location", table_name="standard_segments")
    op.drop_table("standard_segments")
    op.drop_table("standard_indicators")
    op.drop_index("ix_reference_standard_versions_standard_status", table_name="reference_standard_versions")
    op.drop_constraint("fk_reference_standards_current_version", "reference_standards", type_="foreignkey")
    op.drop_table("reference_standard_versions")
    op.drop_table("reference_standards")
