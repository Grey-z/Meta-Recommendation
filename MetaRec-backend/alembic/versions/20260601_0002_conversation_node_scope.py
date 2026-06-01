"""scope conversation node primary key by conversation

Revision ID: 20260601_0002
Revises: 20260530_0001
Create Date: 2026-06-01
"""

from __future__ import annotations

from alembic import op


revision = "20260601_0002"
down_revision = "20260530_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("conversation_nodes_pkey", "conversation_nodes", type_="primary")
    op.create_primary_key("conversation_nodes_pkey", "conversation_nodes", ["conversation_id", "id"])


def downgrade() -> None:
    op.drop_constraint("conversation_nodes_pkey", "conversation_nodes", type_="primary")
    op.create_primary_key("conversation_nodes_pkey", "conversation_nodes", ["id"])
