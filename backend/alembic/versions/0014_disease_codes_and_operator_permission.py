"""add stable disease codes and operator permission

Revision ID: 0014
Revises: 0013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EXPECTED_DISEASES = {
    "脂肪肝": "fatty_liver",
    "阿尔茨海默病": "ad",
}


def _rows(bind, sql: str) -> list[dict]:
    return [dict(row) for row in bind.execute(sa.text(sql)).mappings().all()]


def _count(bind, table: str, where: str = "TRUE") -> int:
    return int(
        bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {where}"))
        .scalar_one()
    )


def _replace_disease_foreign_keys(*, downgrade: bool = False) -> None:
    targets = (
        ("fk_operator_cases_disease", "operator_cases", "CASCADE" if downgrade else "RESTRICT"),
        ("fk_case_records_disease", "case_records", "CASCADE" if downgrade else "RESTRICT"),
        ("fk_ai_reports_disease", "ai_reports", "SET NULL" if downgrade else "RESTRICT"),
    )
    for constraint_name, table_name, ondelete in targets:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            "diseases",
            ["disease_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    op.add_column(
        "diseases",
        sa.Column("code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "diseases",
        sa.Column(
            "operator_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE diseases, operator_cases, case_records, ai_reports, "
            "reference_standards IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    diseases = _rows(bind, "SELECT id, name FROM diseases ORDER BY id")
    related_counts = {
        "operator_cases": _count(bind, "operator_cases"),
        "case_records": _count(bind, "case_records"),
        "ai_reports": _count(bind, "ai_reports", "disease_id IS NOT NULL"),
        "reference_standards": _count(bind, "reference_standards"),
    }

    if not diseases:
        if any(related_counts.values()):
            raise RuntimeError("0014 empty diseases catalog has related business data")
        for name, code in EXPECTED_DISEASES.items():
            bind.execute(
                sa.text(
                    "INSERT INTO diseases (name, code, operator_enabled) "
                    "VALUES (:name, :code, true)"
                ),
                {"name": name, "code": code},
            )
    elif (
        len(diseases) != len(EXPECTED_DISEASES)
        or {row["name"] for row in diseases} != set(EXPECTED_DISEASES)
    ):
        raise RuntimeError("0014 unexpected diseases; manual review required")
    else:
        for name, code in EXPECTED_DISEASES.items():
            bind.execute(
                sa.text(
                    "UPDATE diseases SET code=:code, operator_enabled=true "
                    "WHERE name=:name"
                ),
                {"name": name, "code": code},
            )

    if _count(bind, "diseases", "code IS NULL"):
        raise RuntimeError("0014 failed to assign every disease code")

    op.alter_column(
        "diseases",
        "code",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_unique_constraint("uq_diseases_code", "diseases", ["code"])
    op.create_check_constraint(
        "ck_diseases_code_format",
        "diseases",
        "code ~ '^[a-z][a-z0-9_]*$'",
    )
    _replace_disease_foreign_keys()


def downgrade() -> None:
    _replace_disease_foreign_keys(downgrade=True)
    op.drop_constraint("ck_diseases_code_format", "diseases", type_="check")
    op.drop_constraint("uq_diseases_code", "diseases", type_="unique")
    op.drop_column("diseases", "operator_enabled")
    op.drop_column("diseases", "code")
