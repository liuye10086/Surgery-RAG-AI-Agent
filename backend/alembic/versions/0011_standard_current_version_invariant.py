"""enforce that current standard versions are same-standard approved rows"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INVALID_CURRENT_SQL = """
SELECT count(*)
FROM reference_standards rs
LEFT JOIN reference_standard_versions v ON v.id = rs.current_version_id
WHERE rs.current_version_id IS NOT NULL
  AND (v.id IS NULL OR v.standard_id <> rs.id OR v.status <> 'approved')
"""


def upgrade() -> None:
    bind = op.get_bind()
    if int(bind.execute(sa.text(_INVALID_CURRENT_SQL)).scalar_one()):
        raise RuntimeError(
            "0011 found invalid current standard version; manual review is required and no rows were changed"
        )

    op.execute(sa.text("""
CREATE FUNCTION enforce_reference_standard_current_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM reference_standards rs
    LEFT JOIN reference_standard_versions v ON v.id = rs.current_version_id
    WHERE rs.current_version_id IS NOT NULL
      AND (v.id IS NULL OR v.standard_id <> rs.id OR v.status <> 'approved')
  ) THEN
    RAISE EXCEPTION 'current_version_id must reference an approved version of the same standard'
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
"""))
    op.execute(sa.text("""
CREATE CONSTRAINT TRIGGER ck_reference_standards_current_version_deferred
AFTER INSERT OR UPDATE OF current_version_id ON reference_standards
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_reference_standard_current_version();
"""))
    op.execute(sa.text("""
CREATE CONSTRAINT TRIGGER ck_reference_standard_versions_current_target_deferred
AFTER INSERT OR UPDATE OR DELETE ON reference_standard_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_reference_standard_current_version();
"""))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS ck_reference_standard_versions_current_target_deferred ON reference_standard_versions"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS ck_reference_standards_current_version_deferred ON reference_standards"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_reference_standard_current_version()"))
