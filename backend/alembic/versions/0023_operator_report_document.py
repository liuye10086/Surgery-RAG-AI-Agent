"""Persist immutable complete report documents without changing historical rows."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

CONSTRAINTS = {
    "ck_ai_reports_document_object": "report_document IS NULL OR jsonb_typeof(report_document) = 'object'",
    "ck_ai_reports_document_sha256": "report_document_sha256 IS NULL OR report_document_sha256 ~ '^[0-9a-f]{64}$'",
    "ck_ai_reports_fingerprint_version": "generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2')",
    "ck_ai_reports_v2_publication": "generation_fingerprint_version IS DISTINCT FROM 'v2' OR (report_document IS NOT NULL AND report_document_sha256 IS NOT NULL AND generation_fingerprint IS NOT NULL AND status = 'completed')",
}


def upgrade():
    op.add_column(
        "ai_reports", sa.Column("report_document", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "ai_reports", sa.Column("report_document_sha256", sa.String(64), nullable=True)
    )
    op.add_column(
        "ai_reports",
        sa.Column("generation_fingerprint_version", sa.String(8), nullable=True),
    )
    for name, condition in CONSTRAINTS.items():
        op.create_check_constraint(name, "ai_reports", condition)


def downgrade():
    for name in reversed(CONSTRAINTS):
        op.drop_constraint(name, "ai_reports", type_="check")
    for column in [
        "generation_fingerprint_version",
        "report_document_sha256",
        "report_document",
    ]:
        op.drop_column("ai_reports", column)
