"""收紧业务外键并补齐查询索引。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name, column_name in (
        ("chunks", "document_id"),
        ("sessions", "user_id"),
        ("messages", "session_id"),
    ):
        count = op.get_bind().execute(
            sa.text(
                f'SELECT COUNT(*) FROM "{table_name}" '
                f'WHERE "{column_name}" IS NULL'
            )
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"无法收紧 {table_name}.{column_name}：存在 {count} 条空值记录"
            )

    op.alter_column(
        "chunks", "document_id", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "sessions", "user_id", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "messages", "session_id", existing_type=sa.Integer(), nullable=False
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_session_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.alter_column(
        "messages", "session_id", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "sessions", "user_id", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "chunks", "document_id", existing_type=sa.Integer(), nullable=True
    )
