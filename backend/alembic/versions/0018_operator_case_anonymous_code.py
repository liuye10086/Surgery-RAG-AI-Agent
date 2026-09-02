"""Add nullable unique anonymous codes for operator cases."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operator_cases", sa.Column("anonymous_case_code", sa.String(length=14), nullable=True))
    op.create_unique_constraint(
        "uq_operator_cases_anonymous_case_code",
        "operator_cases",
        ["anonymous_case_code"],
    )
    op.add_column("case_records", sa.Column("anonymous_case_code", sa.String(length=14), nullable=True))


def downgrade() -> None:
    op.drop_constraint("uq_operator_cases_anonymous_case_code", "operator_cases", type_="unique")
    op.drop_column("operator_cases", "anonymous_case_code")
    op.drop_column("case_records", "anonymous_case_code")
