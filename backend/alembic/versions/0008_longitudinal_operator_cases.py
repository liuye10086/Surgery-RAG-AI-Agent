"""add operator-owned longitudinal cases and visits

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operator_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_operator_cases_user", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "disease_id",
            sa.Integer(),
            sa.ForeignKey(
                "diseases.id", name="fk_operator_cases_disease", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("patient_label", sa.String(length=100), nullable=False),
        sa.Column("sex", sa.String(length=10)),
        sa.Column("baseline_stage", sa.String(length=100)),
        sa.Column("notes", sa.Text()),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_operator_cases_user_id", "operator_cases", ["user_id"])
    op.create_index("ix_operator_cases_disease_id", "operator_cases", ["disease_id"])

    op.create_table(
        "operator_case_visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey(
                "operator_cases.id",
                name="fk_operator_case_visits_case",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("visit_index", sa.Integer(), nullable=False),
        sa.Column(
            "indicators",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "case_id", "visit_date", name="uq_operator_case_visits_case_date"
        ),
    )
    op.create_index("ix_operator_case_visits_case_id", "operator_case_visits", ["case_id"])
    op.create_index(
        "ix_operator_case_visits_visit_date", "operator_case_visits", ["visit_date"]
    )

    op.add_column(
        "ai_reports",
        sa.Column(
            "operator_case_id",
            sa.Integer(),
            sa.ForeignKey(
                "operator_cases.id",
                name="fk_ai_reports_operator_case",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.add_column("ai_reports", sa.Column("input_snapshot", JSONB(), nullable=True))
    op.create_index("ix_ai_reports_operator_case_id", "ai_reports", ["operator_case_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_reports_operator_case_id", table_name="ai_reports")
    op.drop_constraint("fk_ai_reports_operator_case", "ai_reports", type_="foreignkey")
    op.drop_column("ai_reports", "input_snapshot")
    op.drop_column("ai_reports", "operator_case_id")

    op.drop_constraint(
        "fk_operator_case_visits_case", "operator_case_visits", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_operator_case_visits_case_date", "operator_case_visits", type_="unique"
    )
    op.drop_index("ix_operator_case_visits_visit_date", table_name="operator_case_visits")
    op.drop_index("ix_operator_case_visits_case_id", table_name="operator_case_visits")
    op.drop_table("operator_case_visits")

    op.drop_constraint("fk_operator_cases_user", "operator_cases", type_="foreignkey")
    op.drop_constraint("fk_operator_cases_disease", "operator_cases", type_="foreignkey")
    op.drop_index("ix_operator_cases_disease_id", table_name="operator_cases")
    op.drop_index("ix_operator_cases_user_id", table_name="operator_cases")
    op.drop_table("operator_cases")
