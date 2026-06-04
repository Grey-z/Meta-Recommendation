"""create business tables

Revision ID: 20260530_0001
Revises:
Create Date: 2026-05-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260530_0001"
down_revision = None
branch_labels = None
depends_on = None


def _jsonb_type():
    return postgresql.JSONB(astext_type=sa.Text())


def _jsonb_default(default: str = "'{}'::jsonb"):
    return sa.text(default)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="guest"),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "anonymous_devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("device_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("session_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_hash"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("anonymous_device_id", sa.String(length=36), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.ForeignKeyConstraint(["anonymous_device_id"], ["anonymous_devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("demographics", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("dining_habits", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False, server_default="New Chat"),
        sa.Column("model", sa.String(length=120), nullable=False, server_default="Auto"),
        sa.Column("last_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("active_branch_id", sa.String(length=128), nullable=False, server_default="branch-main"),
        sa.Column("branch_selection_state", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("preferences", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])

    op.create_table(
        "conversation_branches",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("parent_branch_id", sa.String(length=128), nullable=True),
        sa.Column("fork_from_message_id", sa.String(length=128), nullable=True),
        sa.Column("root_message_id", sa.String(length=128), nullable=True),
        sa.Column("head_message_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "conversation_id"),
    )

    op.create_table(
        "conversation_nodes",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("branch_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("parent_message_id", sa.String(length=128), nullable=True),
        sa.Column("fork_from_message_id", sa.String(length=128), nullable=True),
        sa.Column("revision_of_message_id", sa.String(length=128), nullable=True),
        sa.Column("state", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_nodes_conversation_branch",
        "conversation_nodes",
        ["conversation_id", "branch_id"],
    )
    op.create_index("ix_conversation_nodes_parent", "conversation_nodes", ["conversation_id", "parent_message_id"])

    op.create_table(
        "recommendation_tasks",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("branch_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_recommendation_tasks_scope",
        "recommendation_tasks",
        ["user_id", "conversation_id", "task_id"],
    )

    op.create_table(
        "recommendation_results",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("branch_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("domain", sa.String(length=80), nullable=True),
        sa.Column("restaurants", _jsonb_type(), nullable=False, server_default=_jsonb_default("'[]'::jsonb")),
        sa.Column("thinking_steps", _jsonb_type(), nullable=False, server_default=_jsonb_default("'[]'::jsonb")),
        sa.Column("payload", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index(
        "ix_recommendation_results_scope",
        "recommendation_results",
        ["user_id", "conversation_id", "branch_id"],
    )

    op.create_table(
        "feedback",
        sa.Column("feedback_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("branch_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("payload", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("metadata", _jsonb_type(), nullable=False, server_default=_jsonb_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("feedback_id"),
        sa.UniqueConstraint("user_id", "result_id", "message_id", name="uq_feedback_user_result_message"),
    )
    op.create_index("ix_feedback_scope", "feedback", ["user_id", "conversation_id", "branch_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_scope", table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_recommendation_results_scope", table_name="recommendation_results")
    op.drop_table("recommendation_results")
    op.drop_index("ix_recommendation_tasks_scope", table_name="recommendation_tasks")
    op.drop_table("recommendation_tasks")
    op.drop_index("ix_conversation_nodes_parent", table_name="conversation_nodes")
    op.drop_index("ix_conversation_nodes_conversation_branch", table_name="conversation_nodes")
    op.drop_table("conversation_nodes")
    op.drop_table("conversation_branches")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("user_profiles")
    op.drop_table("user_sessions")
    op.drop_table("anonymous_devices")
    op.drop_table("users")
