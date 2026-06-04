"""schema hardening: FK constraints, operational indexes, feedback unique fix

Revision ID: 20260602_0003
Revises: 20260601_0002
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260602_0003"
down_revision = "20260601_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. FK: recommendation_results.task_id → recommendation_tasks.task_id
    #    SET NULL so result audit records survive task deletion.
    op.create_foreign_key(
        "fk_recommendation_results_task_id",
        "recommendation_results",
        "recommendation_tasks",
        ["task_id"],
        ["task_id"],
        ondelete="SET NULL",
    )

    # 2. Index for crash-recovery startup query:
    #    SELECT * FROM recommendation_tasks WHERE status = 'processing' ORDER BY created_at
    #    Use CONCURRENTLY in production to avoid table lock; omit here for migration safety.
    op.create_index(
        "ix_recommendation_tasks_status_created",
        "recommendation_tasks",
        ["status", "created_at"],
    )

    # 3. Index for session cleanup:
    #    SELECT ... WHERE user_id = ? AND status = 'active' AND expires_at < now()
    op.create_index(
        "ix_user_sessions_user_status_expires",
        "user_sessions",
        ["user_id", "status", "expires_at"],
    )

    # 4. Fix feedback unique constraint: PostgreSQL NULL != NULL, so the existing
    #    UNIQUE(user_id, result_id, message_id) allows duplicate rows when result_id IS NULL.
    #    Replace with two partial unique indexes covering each case.
    op.drop_constraint("uq_feedback_user_result_message", "feedback", type_="unique")
    op.create_index(
        "ix_feedback_uq_with_result",
        "feedback",
        ["user_id", "result_id", "message_id"],
        unique=True,
        postgresql_where=sa.text("result_id IS NOT NULL"),
    )
    op.create_index(
        "ix_feedback_uq_no_result",
        "feedback",
        ["user_id", "message_id"],
        unique=True,
        postgresql_where=sa.text("result_id IS NULL"),
    )

    # 5. FK: conversation_branches → conversation_nodes (composite PK after migration 0002).
    #    Added as NOT VALID to skip existing-row scan (avoids lock), then validated separately.
    #    SET NULL: a deleted node clears the branch pointer rather than cascading the delete.
    op.execute(
        """
        ALTER TABLE conversation_branches
            ADD CONSTRAINT fk_branches_head_message
            FOREIGN KEY (conversation_id, head_message_id)
            REFERENCES conversation_nodes (conversation_id, id)
            ON DELETE SET NULL
            NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE conversation_branches VALIDATE CONSTRAINT fk_branches_head_message"
    )

    op.execute(
        """
        ALTER TABLE conversation_branches
            ADD CONSTRAINT fk_branches_root_message
            FOREIGN KEY (conversation_id, root_message_id)
            REFERENCES conversation_nodes (conversation_id, id)
            ON DELETE SET NULL
            NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE conversation_branches VALIDATE CONSTRAINT fk_branches_root_message"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_branches DROP CONSTRAINT IF EXISTS fk_branches_root_message"
    )
    op.execute(
        "ALTER TABLE conversation_branches DROP CONSTRAINT IF EXISTS fk_branches_head_message"
    )

    op.drop_index("ix_feedback_uq_no_result", table_name="feedback")
    op.drop_index("ix_feedback_uq_with_result", table_name="feedback")
    op.create_unique_constraint(
        "uq_feedback_user_result_message",
        "feedback",
        ["user_id", "result_id", "message_id"],
    )

    op.drop_index("ix_user_sessions_user_status_expires", table_name="user_sessions")
    op.drop_index("ix_recommendation_tasks_status_created", table_name="recommendation_tasks")

    op.drop_constraint(
        "fk_recommendation_results_task_id",
        "recommendation_results",
        type_="foreignkey",
    )
