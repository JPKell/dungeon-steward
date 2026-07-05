"""Add timed potion inventory and activation history.

Revision ID: 20260703_0003
Revises: 20260703_0002
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260703_0003"
down_revision = "20260703_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "potion_inventory_stacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("item_key", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_potion_inventory_quantity_nonnegative"),
        sa.UniqueConstraint("player_id", "item_key", name="uq_potion_inventory_player_item"),
    )
    op.create_index("ix_potion_inventory_player", "potion_inventory_stacks", ["player_id"])

    op.create_table(
        "potion_activations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("item_key", sa.String(length=120), nullable=False),
        sa.Column("effect_group", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_token", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("player_id", "idempotency_token", name="uq_potion_activation_player_token"),
    )
    op.create_index(
        "ix_potion_activation_player_time",
        "potion_activations",
        ["player_id", "activated_at", "effective_ends_at"],
    )
    op.create_index(
        "ix_potion_activation_player_group",
        "potion_activations",
        ["player_id", "effect_group", "effective_ends_at"],
    )

    with op.batch_alter_table("encounter_history") as batch_op:
        batch_op.add_column(sa.Column("potion_item_key", sa.String(length=120)))


def downgrade() -> None:
    with op.batch_alter_table("encounter_history") as batch_op:
        batch_op.drop_column("potion_item_key")
    op.drop_index("ix_potion_activation_player_group", table_name="potion_activations")
    op.drop_index("ix_potion_activation_player_time", table_name="potion_activations")
    op.drop_table("potion_activations")
    op.drop_index("ix_potion_inventory_player", table_name="potion_inventory_stacks")
    op.drop_table("potion_inventory_stacks")
