"""Constrain operator case statuses and add immutable transition audit."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _preflight(bind) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT status, count(*) AS count FROM operator_cases "
            "GROUP BY status ORDER BY status"
        )
    ).mappings().all()
    invalid = [row for row in rows if row["status"] not in ("active", "archived")]
    if invalid:
        raise RuntimeError(
            "0015 unexpected operator_cases.status values; manual review required: "
            + repr([dict(row) for row in invalid])
        )


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    op.create_table(
        "operator_case_status_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("operator_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("case_id_snapshot", sa.Integer(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=False),
        sa.Column("to_status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "from_status IN ('active', 'archived') AND to_status IN ('active', 'archived')",
            name="ck_operator_case_status_logs_values",
        ),
        sa.CheckConstraint(
            "from_status <> to_status", name="ck_operator_case_status_logs_changed"
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 500",
            name="ck_operator_case_status_logs_reason",
        ),
    )
    op.create_index(
        "ix_operator_case_status_logs_case_time",
        "operator_case_status_logs",
        ["case_id_snapshot", "created_at"],
    )
    op.create_index(
        "ix_operator_case_status_logs_actor_time",
        "operator_case_status_logs",
        ["actor_id_snapshot", "created_at"],
    )
    op.execute(
        "ALTER TABLE operator_cases ALTER COLUMN status SET DEFAULT 'active'"
    )
    op.execute("ALTER TABLE operator_cases ALTER COLUMN status SET NOT NULL")
    op.execute(
        "ALTER TABLE operator_cases ADD CONSTRAINT ck_operator_cases_status "
        "CHECK (status IN ('active', 'archived')) NOT VALID"
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = int(
        bind.execute(sa.text("SELECT count(*) FROM operator_case_status_logs")).scalar_one()
    )
    if count:
        raise RuntimeError("0015 downgrade blocked: status audit history is not empty")
    op.drop_constraint("ck_operator_cases_status", "operator_cases", type_="check")
    op.drop_index(
        "ix_operator_case_status_logs_actor_time", table_name="operator_case_status_logs"
    )
    op.drop_index(
        "ix_operator_case_status_logs_case_time", table_name="operator_case_status_logs"
    )
    op.drop_table("operator_case_status_logs")

