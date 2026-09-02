"""Add report integrity and generation-state audit fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_reports", sa.Column("input_snapshot_sha256", sa.String(length=64), nullable=True))
    op.add_column("ai_reports", sa.Column("generation_batch_id", sa.String(length=36), nullable=True))
    op.add_column("ai_reports", sa.Column("generation_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("ai_reports", sa.Column("error_stage", sa.String(length=50), nullable=True))
    op.create_index("ix_ai_reports_generation_batch_id", "ai_reports", ["generation_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_reports_generation_batch_id", table_name="ai_reports")
    op.drop_column("ai_reports", "error_stage")
    op.drop_column("ai_reports", "generation_fingerprint")
    op.drop_column("ai_reports", "generation_batch_id")
    op.drop_column("ai_reports", "input_snapshot_sha256")
