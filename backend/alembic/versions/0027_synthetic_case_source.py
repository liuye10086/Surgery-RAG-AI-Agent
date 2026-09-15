"""Persist explicit engineering provenance without relabeling existing cases."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operator_cases", sa.Column("engineering_source", postgresql.JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint(
        "ck_operator_cases_engineering_source", "operator_cases",
        "engineering_source IS NULL OR (jsonb_typeof(engineering_source) = 'object' "
        "AND (engineering_source->>'schema_version' = 'synthetic_case_source.v1') IS TRUE "
        "AND (engineering_source->>'source_kind' = 'synthetic') IS TRUE "
        "AND (engineering_source->'is_synthetic' = 'true'::jsonb) IS TRUE)",
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM operator_cases WHERE engineering_source IS NOT NULL)")).scalar():
        raise RuntimeError("synthetic_source_downgrade_would_discard_provenance")
    op.drop_constraint("ck_operator_cases_engineering_source", "operator_cases", type_="check")
    op.drop_column("operator_cases", "engineering_source")
