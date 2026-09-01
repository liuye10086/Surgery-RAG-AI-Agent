"""add age to AI operator longitudinal cases"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operator_cases",
        sa.Column("age", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_operator_cases_age_range",
        "operator_cases",
        "age IS NULL OR age BETWEEN 0 AND 120",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_operator_cases_age_range",
        "operator_cases",
        type_="check",
    )
    op.drop_column("operator_cases", "age")
