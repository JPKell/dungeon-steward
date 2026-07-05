"""Add administration audit log.

Revision ID: 20260703_0004
Revises: 20260703_0003
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260703_0004"
down_revision = "20260703_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("administrator_identity", sa.String(length=160), nullable=False),
        sa.Column("administrator_role", sa.String(length=40), nullable=False),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("action_name", sa.String(length=160), nullable=False),
        sa.Column("target_domain", sa.String(length=80), nullable=False),
        sa.Column("target_table", sa.String(length=120)),
        sa.Column("target_user_id", sa.Integer()),
        sa.Column("target_record_id", sa.String(length=160)),
        sa.Column("previous_values", sa.Text()),
        sa.Column("new_values", sa.Text()),
        sa.Column("quantity_changed", sa.Integer()),
        sa.Column("reason", sa.Text()),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("error_info", sa.Text()),
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_audit_admin_created",
        "admin_audit_log",
        ["administrator_identity", "created_at"],
    )
    op.create_index("ix_admin_audit_target_user", "admin_audit_log", ["target_user_id", "created_at"])
    op.create_index("ix_admin_audit_action", "admin_audit_log", ["action_name", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_action", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_target_user", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_admin_created", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
