"""drop unused per-node usage columns from conversation_nodes

The per-message token/cost/latency columns were never populated: the frontend
(which persists assistant turns) never sends ``metadata.stats``, and the admin
dashboard's token figures are aggregated from the ``llm_usage_events`` log
instead. Dropping them removes a dead write path.

Revision ID: 20260702_0006
Revises: 20260604_0005
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260702_0006"
down_revision = "20260604_0005"
branch_labels = None
depends_on = None

_USAGE_COLUMNS = ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd", "latency_ms")


def upgrade() -> None:
    for column in _USAGE_COLUMNS:
        op.drop_column("conversation_nodes", column)


def downgrade() -> None:
    op.add_column("conversation_nodes", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_nodes", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_nodes", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_nodes", sa.Column("cost_usd", sa.Float(), nullable=True))
    op.add_column("conversation_nodes", sa.Column("latency_ms", sa.Integer(), nullable=True))
