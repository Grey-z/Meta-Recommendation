"""add item_interactions table (user x item signal behind /api/item-interactions)

The existing ``feedback`` table is result-level — it has no item id — so it
cannot feed a recommender. This table records one user action on one
recommended item: ``save``/``hide`` toggles (one active row each, undo via
``revoked_at``) and ``positive``/``negative``/``consumed`` append-only events.
See ``business_repositories.PostgresItemInteractionRepository`` for semantics.

Revision ID: 20260821_0007
Revises: 20260702_0006
Create Date: 2026-08-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260821_0007"
down_revision = "20260702_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_interactions",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=40), nullable=False),
        sa.Column("item_id", sa.String(length=512), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('save', 'hide', 'positive', 'negative', 'consumed')",
            name="ck_item_interactions_action",
        ),
    )
    # Ranker read path: one user's history in one domain, chronological.
    op.create_index(
        "ix_item_interactions_user_domain_time",
        "item_interactions",
        ["user_id", "domain", "occurred_at"],
    )
    # Toggle-state lookup for the UI ("is this item already saved/hidden?").
    op.create_index(
        "ix_item_interactions_user_domain_item",
        "item_interactions",
        ["user_id", "domain", "item_id"],
    )
    # At most one ACTIVE save and one ACTIVE hide per (user, domain, item). Events
    # (positive/negative/consumed) are deliberately excluded so repeats are kept.
    op.create_index(
        "ix_item_interactions_uq_active_toggle",
        "item_interactions",
        ["user_id", "domain", "item_id", "action"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL AND action IN ('save', 'hide')"),
    )


def downgrade() -> None:
    op.drop_index("ix_item_interactions_uq_active_toggle", table_name="item_interactions")
    op.drop_index("ix_item_interactions_user_domain_item", table_name="item_interactions")
    op.drop_index("ix_item_interactions_user_domain_time", table_name="item_interactions")
    op.drop_table("item_interactions")
