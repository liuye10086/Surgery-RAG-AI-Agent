"""Validate the operator case status check separately from its creation."""

from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE operator_cases VALIDATE CONSTRAINT ck_operator_cases_status"
    )


def downgrade() -> None:
    # PostgreSQL has no UNVALIDATE command. Recreate the same constraint as
    # NOT VALID without touching any case or audit business rows.
    op.execute(
        "ALTER TABLE operator_cases DROP CONSTRAINT ck_operator_cases_status"
    )
    op.execute(
        "ALTER TABLE operator_cases ADD CONSTRAINT ck_operator_cases_status "
        "CHECK (status IN ('active', 'archived')) NOT VALID"
    )

