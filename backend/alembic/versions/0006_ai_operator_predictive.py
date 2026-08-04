"""add diseases, case_records, reference_ranges, ai_reports predictive columns

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diseases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "case_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("disease_id", sa.Integer(), sa.ForeignKey("diseases.id", name="fk_case_records_disease", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_label", sa.String(length=100)),
        sa.Column("indicators", JSONB(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_case_records_disease_id", "case_records", ["disease_id"])
    op.create_table(
        "reference_ranges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("indicator_name", sa.String(length=100), nullable=False),
        sa.Column("name_cn", sa.String(length=200)),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("lower", sa.Float()),
        sa.Column("upper", sa.Float()),
        sa.Column("lower_inclusive", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("upper_inclusive", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("category", sa.String(length=100)),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", name="fk_reference_ranges_document", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reference_ranges_indicator", "reference_ranges", ["indicator_name"])
    op.add_column("ai_reports", sa.Column("analysis_type", sa.String(length=50), nullable=False, server_default="retrospective"))
    op.add_column("ai_reports", sa.Column("disease_id", sa.Integer(), sa.ForeignKey("diseases.id", name="fk_ai_reports_disease", ondelete="SET NULL")))
    # server_default 使 ADD COLUMN 立即回填既有行为 []::jsonb / {}::jsonb，
    # 与 ORM 与 schema.sql 保持一致，避免旧报告行这两列为 NULL。
    op.add_column("ai_reports", sa.Column("indicators", JSONB(), server_default=sa.text("'[]'::jsonb")))
    op.add_column("ai_reports", sa.Column("prediction_result", JSONB(), server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("ai_reports", "prediction_result")
    op.drop_column("ai_reports", "indicators")
    # 显式先删外键约束再删列，保证 downgrade 对称（PostgreSQL 不会自动删约束）
    op.drop_constraint("fk_ai_reports_disease", "ai_reports", type_="foreignkey")
    op.drop_column("ai_reports", "disease_id")
    op.drop_column("ai_reports", "analysis_type")
    op.drop_index("ix_reference_ranges_indicator", table_name="reference_ranges")
    op.drop_table("reference_ranges")
    op.drop_index("ix_case_records_disease_id", table_name="case_records")
    op.drop_table("case_records")
    op.drop_table("diseases")
