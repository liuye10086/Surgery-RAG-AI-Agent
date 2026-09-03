"""Add structured context to operator case visits."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operator_case_visits",
        sa.Column(
            "visit_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_operator_case_visits_visit_context_object",
        "operator_case_visits",
        "jsonb_typeof(visit_context) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_operator_case_visits_visit_context_object",
        "operator_case_visits",
        type_="check",
    )
    op.drop_column("operator_case_visits", "visit_context")
