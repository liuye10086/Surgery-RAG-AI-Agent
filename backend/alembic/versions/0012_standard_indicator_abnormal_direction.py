"""persist canonical indicator abnormal direction"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REVIEWED_DIRECTIONS = {
    "alt": "high",
    "ast": "high",
    "ggt": "high",
    "tbil": "high",
    "alb": "low",
    "hba1c": "high",
    "bmi": "high",
    "waist": "high",
    "plt": "contextual",
    "afp": "contextual",
    "mmse": "ordinal_low",
    "moca": "ordinal_low",
    "cdr": "ordinal_high",
    "nfl": "high",
    "p-tau217": "high",
    "aβ42/aβ40": "low",
}


def upgrade() -> None:
    op.add_column(
        "standard_indicators",
        sa.Column(
            "abnormal_direction",
            sa.String(length=50),
            nullable=False,
            server_default="none",
        ),
    )
    bind = op.get_bind()
    for canonical_key, direction in _REVIEWED_DIRECTIONS.items():
        bind.execute(
            sa.text(
                "UPDATE standard_indicators "
                "SET abnormal_direction = :direction "
                "WHERE canonical_key = :canonical_key"
            ),
            {"canonical_key": canonical_key, "direction": direction},
        )
    op.create_check_constraint(
        "ck_standard_indicators_abnormal_direction",
        "standard_indicators",
        "abnormal_direction IN ('high', 'low', 'ordinal_high', 'ordinal_low', 'contextual', 'none')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_standard_indicators_abnormal_direction",
        "standard_indicators",
        type_="check",
    )
    op.drop_column("standard_indicators", "abnormal_direction")
