"""add user role column

Revision ID: 20260603_0004
Revises: 20260602_0003
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260603_0004"
down_revision = "20260602_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Authorization role, stored as VARCHAR to match the existing kind/status
    # convention (no native PG enum). Default 'user'; a CHECK constraint keeps
    # the column to the known set without enum-migration rigidity.
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )
    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('admin', 'user')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.drop_column("users", "role")
