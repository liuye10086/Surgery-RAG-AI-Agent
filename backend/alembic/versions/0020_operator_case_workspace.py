"""Add operator case workspace audit, idempotency, and sex constraints."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels = None
depends_on = None


def _reject_invalid_sex(bind) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT sex, count(*) AS count FROM operator_cases "
            "WHERE sex IS NOT NULL AND sex NOT IN ('male', 'female') "
            "GROUP BY sex ORDER BY sex"
        )
    ).mappings().all()
    if rows:
        counts = {str(row["sex"]): int(row["count"]) for row in rows}
        raise RuntimeError(f"invalid_operator_case_sex: {counts}")


def upgrade() -> None:
    bind = op.get_bind()
    _reject_invalid_sex(bind)

    op.execute(
        sa.text(
            "ALTER TABLE operator_cases "
            "ADD CONSTRAINT ck_operator_cases_sex "
            "CHECK (sex IS NULL OR sex IN ('male', 'female')) NOT VALID"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE operator_cases "
            "VALIDATE CONSTRAINT ck_operator_cases_sex"
        )
    )

    op.create_table(
        "operator_case_change_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("operator_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("case_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("anonymous_case_code_snapshot", sa.String(length=14), nullable=True),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "changes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('created', 'profile_updated', 'timeline_updated', 'case_updated', 'deleted')",
            name="ck_operator_case_change_logs_action",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 500",
            name="ck_operator_case_change_logs_reason",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'object'",
            name="ck_operator_case_change_logs_changes_object",
        ),
    )
    op.create_index(
        "ix_operator_case_change_logs_case_time",
        "operator_case_change_logs",
        ["case_id_snapshot", "created_at"],
    )
    op.create_index(
        "ix_operator_case_change_logs_actor_time",
        "operator_case_change_logs",
        ["actor_id_snapshot", "created_at"],
    )

    op.create_table(
        "operator_idempotency_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column(
            "idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "scope",
            "idempotency_key",
            name="uq_operator_idempotency_user_scope_key",
        ),
        sa.CheckConstraint(
            "scope = 'create_longitudinal_case'",
            name="ck_operator_idempotency_keys_scope",
        ),
        sa.CheckConstraint(
            "resource_type = 'operator_case'",
            name="ck_operator_idempotency_keys_resource_type",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_operator_idempotency_keys_request_sha256",
        ),
    )
    op.create_index(
        "ix_operator_idempotency_keys_user_time",
        "operator_idempotency_keys",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    counts = {
        table: int(
            bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        )
        for table in (
            "operator_case_change_logs",
            "operator_idempotency_keys",
        )
    }
    if any(counts.values()):
        raise RuntimeError(
            "refusing_to_drop_nonempty_operator_case_workspace_evidence"
        )

    op.drop_index(
        "ix_operator_idempotency_keys_user_time",
        table_name="operator_idempotency_keys",
    )
    op.drop_table("operator_idempotency_keys")
    op.drop_index(
        "ix_operator_case_change_logs_actor_time",
        table_name="operator_case_change_logs",
    )
    op.drop_index(
        "ix_operator_case_change_logs_case_time",
        table_name="operator_case_change_logs",
    )
    op.drop_table("operator_case_change_logs")
    op.drop_constraint(
        "ck_operator_cases_sex",
        "operator_cases",
        type_="check",
    )
