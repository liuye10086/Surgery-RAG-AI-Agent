"""Add database floor constraints for operator longitudinal visit indexes."""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_operator_case_visits_visit_index_positive",
        "operator_case_visits",
        "visit_index >= 1",
    )
    op.create_unique_constraint(
        "uq_operator_case_visits_case_id_visit_index",
        "operator_case_visits",
        ["case_id", "visit_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_operator_case_visits_case_id_visit_index",
        "operator_case_visits",
        type_="unique",
    )
    op.drop_constraint(
        "ck_operator_case_visits_visit_index_positive",
        "operator_case_visits",
        type_="check",
    )
