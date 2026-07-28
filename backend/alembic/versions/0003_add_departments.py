"""新增科室表、文档科室外键与索引。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 科室表
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(None, "departments", ["name"])

    # 2. 文档表新增科室外键
    op.add_column(
        "documents",
        sa.Column("department_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        None,
        "documents",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "idx_documents_department_id",
        "documents",
        ["department_id"],
    )

    # 3. 种子数据
    op.execute(
        sa.text(
            """
            INSERT INTO departments (name) VALUES
                ('肝胆外科'),
                ('神经外科'),
                ('骨科'),
                ('心胸外科'),
                ('泌尿外科'),
                ('胃肠外科'),
                ('甲状腺乳腺外科'),
                ('血管外科'),
                ('烧伤整形外科'),
                ('麻醉科'),
                ('其他')
            ON CONFLICT (name) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_documents_department_id", table_name="documents")
    op.drop_constraint(
        None, "documents", type_="foreignkey"
    )
    op.drop_column("documents", "department_id")
    op.drop_table("departments")
