"""Add immutable evidence snapshots and versioned reference-case windows."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("standard_documents", sa.Column("issuer", sa.String(length=300), nullable=True))
    op.add_column("standard_documents", sa.Column("publication_date", sa.Date(), nullable=True))
    op.add_column("standard_documents", sa.Column("external_identifier", sa.String(length=200), nullable=True))
    op.add_column("standard_documents", sa.Column("source_url", sa.String(length=1000), nullable=True))
    op.add_column("standard_segments", sa.Column("page_number", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_standard_segments_page_number_positive",
        "standard_segments",
        "page_number IS NULL OR page_number > 0",
    )

    op.add_column("ai_reports", sa.Column("evidence_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("ai_reports", sa.Column("evidence_snapshot_sha256", sa.String(length=64), nullable=True))
    op.add_column("ai_reports", sa.Column("evidence_status", sa.String(length=20), nullable=True))
    op.add_column("ai_reports", sa.Column("standard_evidence_status", sa.String(length=40), nullable=True))
    op.add_column("ai_reports", sa.Column("reference_case_status", sa.String(length=40), nullable=True))
    op.create_check_constraint(
        "ck_ai_reports_evidence_snapshot_sha256",
        "ai_reports",
        "evidence_snapshot_sha256 IS NULL OR evidence_snapshot_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_ai_reports_evidence_status",
        "ai_reports",
        "evidence_status IS NULL OR evidence_status IN ('complete', 'partial')",
    )
    op.create_check_constraint(
        "ck_ai_reports_standard_evidence_status",
        "ai_reports",
        "standard_evidence_status IS NULL OR standard_evidence_status IN ('available', 'context_incomplete', 'not_applicable', 'conflict')",
    )
    op.create_check_constraint(
        "ck_ai_reports_reference_case_status",
        "ai_reports",
        "reference_case_status IS NULL OR reference_case_status IN ('available', 'no_eligible_cases', 'insufficient_comparability', 'reference_query_failed', 'reference_index_stale')",
    )

    op.create_table(
        "reference_case_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("disease_id", sa.Integer(), sa.ForeignKey("diseases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("logical_dataset", sa.String(length=50), nullable=False),
        sa.Column("dataset_release_id", sa.String(length=100), nullable=False),
        sa.Column("prediction_task", sa.String(length=120), nullable=False),
        sa.Column("anonymous_case_code", sa.String(length=14), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("profile_schema_version", sa.String(length=80), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(length=10), nullable=True),
        sa.Column("baseline_stage", sa.String(length=100), nullable=True),
        sa.Column("visit_count", sa.Integer(), nullable=False),
        sa.Column("span_days", sa.Integer(), nullable=False),
        sa.Column("outcome_status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("outcome_source", sa.String(length=100), nullable=False),
        sa.Column("outcome_reliability", sa.String(length=10), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eligibility_status", sa.String(length=20), nullable=False, server_default="eligible"),
        sa.Column("timeline_sha256", sa.String(length=64), nullable=False),
        sa.Column("eligibility_config_hash", sa.String(length=64), nullable=False),
        sa.Column("data_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("outcome_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("feature_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("measurement_context_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("exclusion_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "dataset_release_id", "anonymous_case_code", "as_of", "horizon_days", "profile_schema_version",
            name="uq_reference_case_windows_case_version",
        ),
        sa.CheckConstraint("anonymous_case_code ~ '^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$'", name="ck_reference_case_windows_anonymous_code"),
        sa.CheckConstraint("horizon_days = 365", name="ck_reference_case_windows_horizon"),
        sa.CheckConstraint("age IS NULL OR age BETWEEN 0 AND 120", name="ck_reference_case_windows_age_range"),
        sa.CheckConstraint("sex IS NULL OR sex IN ('male', 'female')", name="ck_reference_case_windows_sex"),
        sa.CheckConstraint("visit_count >= 3", name="ck_reference_case_windows_min_visits"),
        sa.CheckConstraint("span_days >= 0", name="ck_reference_case_windows_min_span"),
        sa.CheckConstraint("outcome_status IN ('positive', 'negative', 'unknown', 'not_observed')", name="ck_reference_case_windows_outcome_status"),
        sa.CheckConstraint("outcome_reliability IN ('low', 'medium', 'high')", name="ck_reference_case_windows_outcome_reliability"),
        sa.CheckConstraint("eligibility_status IN ('eligible', 'excluded')", name="ck_reference_case_windows_eligibility_status"),
        sa.CheckConstraint("timeline_sha256 ~ '^[0-9a-f]{64}$'", name="ck_reference_case_windows_timeline_sha256"),
        sa.CheckConstraint("eligibility_config_hash ~ '^[0-9a-f]{64}$'", name="ck_reference_case_windows_eligibility_config_hash"),
        sa.CheckConstraint("data_content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_reference_case_windows_data_content_sha256"),
    )
    op.create_index(
        "ix_reference_case_windows_pool_lookup", "reference_case_windows",
        ["disease_id", "dataset_release_id", "eligibility_status", "prediction_task", "baseline_stage"],
    )
    op.create_index("ix_reference_case_windows_case_lookup", "reference_case_windows", ["anonymous_case_code", "as_of"])
    op.create_index(
        "ix_reference_case_windows_feature_summary_gin", "reference_case_windows", ["feature_summary"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "LOCK TABLE reference_case_windows, ai_reports, standard_documents, standard_segments IN SHARE MODE"
    ))
    checks = (
        ("reference_case_windows", "SELECT count(*) FROM reference_case_windows"),
        ("ai_reports", "SELECT count(*) FROM ai_reports WHERE evidence_snapshot IS NOT NULL"),
        ("standard_documents", "SELECT count(*) FROM standard_documents WHERE issuer IS NOT NULL OR publication_date IS NOT NULL OR external_identifier IS NOT NULL OR source_url IS NOT NULL"),
        ("standard_segments", "SELECT count(*) FROM standard_segments WHERE page_number IS NOT NULL"),
    )
    if any(bind.execute(sa.text(sql)).scalar_one() > 0 for _, sql in checks):
        raise RuntimeError("refusing_to_drop_nonempty_longitudinal_evidence")

    op.drop_index("ix_reference_case_windows_feature_summary_gin", table_name="reference_case_windows")
    op.drop_index("ix_reference_case_windows_case_lookup", table_name="reference_case_windows")
    op.drop_index("ix_reference_case_windows_pool_lookup", table_name="reference_case_windows")
    op.drop_table("reference_case_windows")
    for name in (
        "ck_ai_reports_reference_case_status",
        "ck_ai_reports_standard_evidence_status",
        "ck_ai_reports_evidence_status",
        "ck_ai_reports_evidence_snapshot_sha256",
    ):
        op.drop_constraint(name, "ai_reports", type_="check")
    for column in ("reference_case_status", "standard_evidence_status", "evidence_status", "evidence_snapshot_sha256", "evidence_snapshot"):
        op.drop_column("ai_reports", column)
    op.drop_constraint(
        "ck_standard_segments_page_number_positive",
        "standard_segments",
        type_="check",
    )
    op.drop_column("standard_segments", "page_number")
    for column in ("source_url", "external_identifier", "publication_date", "issuer"):
        op.drop_column("standard_documents", column)
