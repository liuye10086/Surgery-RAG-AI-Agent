"""separate standard documents from the knowledge document domain"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _lock_tables(bind, *table_names: str) -> None:
    names = ", ".join(table_names)
    bind.execute(sa.text(f"LOCK TABLE {names} IN SHARE MODE"))


def _row_count(bind, table_name: str) -> int:
    return int(bind.execute(sa.text(f"SELECT count(*) FROM {table_name}")).scalar_one())


def upgrade() -> None:
    bind = op.get_bind()
    _lock_tables(bind, "reference_standard_versions")
    if _row_count(bind, "reference_standard_versions"):
        raise RuntimeError(
            "0010 requires reference_standard_versions to be empty; "
            "manual review is required and no rows were changed"
        )

    op.create_table(
        "standard_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=500)),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("content_hash", name="uq_standard_documents_content_hash"),
    )
    op.create_foreign_key(
        "fk_standard_documents_uploaded_by",
        "standard_documents",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        "reference_standard_versions_document_id_fkey",
        "reference_standard_versions",
        type_="foreignkey",
    )
    op.drop_column("reference_standard_versions", "document_id")
    op.add_column(
        "reference_standard_versions",
        sa.Column("standard_document_id", sa.Integer(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_reference_standard_versions_standard_document",
        "reference_standard_versions",
        ["standard_document_id"],
    )
    op.create_foreign_key(
        "fk_reference_standard_versions_standard_document",
        "reference_standard_versions",
        "standard_documents",
        ["standard_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "reference_standards_disease_id_fkey",
        "reference_standards",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reference_standards_disease_id_fkey",
        "reference_standards",
        "diseases",
        ["disease_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    bind = op.get_bind()
    _lock_tables(bind, "reference_standard_versions", "standard_documents")
    if _row_count(bind, "reference_standard_versions") or _row_count(bind, "standard_documents"):
        raise RuntimeError(
            "0010 downgrade requires reference_standard_versions and "
            "standard_documents to be empty; no rows were changed"
        )

    op.drop_constraint(
        "reference_standards_disease_id_fkey",
        "reference_standards",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reference_standards_disease_id_fkey",
        "reference_standards",
        "diseases",
        ["disease_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_reference_standard_versions_standard_document",
        "reference_standard_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_reference_standard_versions_standard_document",
        "reference_standard_versions",
        type_="unique",
    )
    op.drop_column("reference_standard_versions", "standard_document_id")
    op.add_column(
        "reference_standard_versions",
        sa.Column("document_id", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "reference_standard_versions_document_id_fkey",
        "reference_standard_versions",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "fk_standard_documents_uploaded_by",
        "standard_documents",
        type_="foreignkey",
    )
    op.drop_table("standard_documents")
