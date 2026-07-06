"""Expand weekly objective tracking and rewards.

Revision ID: 20260706_0008
Revises: 20260705_0007
Create Date: 2026-07-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260706_0008"
down_revision = "20260705_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("guild_dungeons") as batch:
        batch.add_column(sa.Column("weekly_difficulty_index", sa.Float(), nullable=False, server_default="1.0"))

    with op.batch_alter_table("weekly_objectives") as batch:
        batch.add_column(sa.Column("metric", sa.String(length=80), nullable=False, server_default="explorations"))
        batch.add_column(sa.Column("mode", sa.String(length=40), nullable=False, server_default="explore"))
        batch.add_column(sa.Column("effort_tier", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("difficulty_index", sa.Float(), nullable=False, server_default="1.0"))
        batch.add_column(sa.Column("previous_participant_count", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("participant_factor", sa.Float(), nullable=False, server_default="1.0"))
        batch.add_column(sa.Column("raw_target_value", sa.Float(), nullable=False, server_default="1.0"))
        batch.add_column(sa.Column("rounded_target_value", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("succeeded", sa.Boolean()))
        batch.add_column(sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("reward_policy_version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("participant_count", sa.Integer(), nullable=False, server_default="0"))

    op.create_index(
        "uq_weekly_guild_active_unresolved",
        "weekly_objectives",
        ["guild_id"],
        unique=True,
        sqlite_where=sa.text("resolved_at IS NULL"),
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    op.create_table(
        "weekly_objective_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weekly_objective_id", sa.Integer(), sa.ForeignKey("weekly_objectives.id"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("unique_key", sa.String(length=160)),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("weekly_objective_id", "event_id", name="uq_weekly_objective_event"),
    )
    op.create_index(
        "ix_weekly_objective_events_metric",
        "weekly_objective_events",
        ["weekly_objective_id", "metric"],
    )
    op.create_index(
        "ix_weekly_objective_events_unique",
        "weekly_objective_events",
        ["weekly_objective_id", "metric", "unique_key"],
    )
    op.create_table(
        "weekly_objective_rewards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("objective_id", sa.Integer(), sa.ForeignKey("weekly_objectives.id"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("explore_level_used", sa.Integer(), nullable=False),
        sa.Column("reference_equipment_cost", sa.Integer(), nullable=False),
        sa.Column("effort_multiplier", sa.Float(), nullable=False),
        sa.Column("difficulty_multiplier", sa.Float(), nullable=False),
        sa.Column("contribution", sa.Integer(), nullable=False),
        sa.Column("minimum_required_contribution", sa.Integer(), nullable=False),
        sa.Column("gold_awarded", sa.Integer(), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("objective_id", "user_id", name="uq_weekly_objective_reward_user"),
    )
    op.create_index(
        "ix_weekly_objective_rewards_objective",
        "weekly_objective_rewards",
        ["objective_id", "awarded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_weekly_objective_rewards_objective", table_name="weekly_objective_rewards")
    op.drop_table("weekly_objective_rewards")
    op.drop_index("ix_weekly_objective_events_unique", table_name="weekly_objective_events")
    op.drop_index("ix_weekly_objective_events_metric", table_name="weekly_objective_events")
    op.drop_table("weekly_objective_events")
    op.drop_index("uq_weekly_guild_active_unresolved", table_name="weekly_objectives")
    with op.batch_alter_table("weekly_objectives") as batch:
        batch.drop_column("participant_count")
        batch.drop_column("reward_policy_version")
        batch.drop_column("schema_version")
        batch.drop_column("succeeded")
        batch.drop_column("rounded_target_value")
        batch.drop_column("raw_target_value")
        batch.drop_column("participant_factor")
        batch.drop_column("previous_participant_count")
        batch.drop_column("difficulty_index")
        batch.drop_column("effort_tier")
        batch.drop_column("mode")
        batch.drop_column("metric")
    with op.batch_alter_table("guild_dungeons") as batch:
        batch.drop_column("weekly_difficulty_index")
