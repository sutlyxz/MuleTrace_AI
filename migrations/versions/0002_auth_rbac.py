"""Add authentication and RBAC schema: users, auth_sessions, auth_audit_logs.

Revision ID: 0002_auth_rbac
Revises: 0001_initial_schema
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_auth_rbac"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID = sa.String(64)


def upgrade() -> None:
    # 1. users table
    op.create_table(
        "users",
        sa.Column("id", ID, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), server_default=sa.text("'user'"), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # 2. auth_sessions table
    op.create_table(
        "auth_sessions",
        sa.Column("id", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])

    # 3. auth_audit_logs table
    op.create_table(
        "auth_audit_logs",
        sa.Column("id", ID, nullable=False),
        sa.Column("actor_user_id", ID, nullable=True),
        sa.Column("target_user_id", ID, nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("safe_metadata", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_audit_logs"),
    )
    op.create_index("ix_auth_audit_logs_actor", "auth_audit_logs", ["actor_user_id"])
    op.create_index("ix_auth_audit_logs_target", "auth_audit_logs", ["target_user_id"])
    op.create_index("ix_auth_audit_logs_action", "auth_audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("auth_audit_logs")
    op.drop_table("auth_sessions")
    op.drop_table("users")
