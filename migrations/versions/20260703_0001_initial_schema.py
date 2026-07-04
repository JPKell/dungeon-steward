"""Initial Dungeon Steward schema.

Revision ID: 20260703_0001
Revises:
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260703_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("image_url", sa.String(length=500)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "guild_dungeons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("discord_guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("gold", sa.Integer(), nullable=False),
        sa.Column("hero_influence", sa.Integer(), nullable=False),
        sa.Column("villain_influence", sa.Integer(), nullable=False),
        sa.Column("stability", sa.Integer(), nullable=False),
        sa.Column("total_explorations", sa.Integer(), nullable=False),
        sa.Column("heroes_defeated", sa.Integer(), nullable=False),
        sa.Column("rooms_discovered", sa.Integer(), nullable=False),
        sa.Column("current_week_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("discord_guild_id"),
    )
    op.create_index("ix_guild_dungeons_discord_guild_id", "guild_dungeons", ["discord_guild_id"])
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("gold", sa.Integer(), nullable=False),
        sa.Column("experience", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=False),
        sa.Column("energy_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_explorations", sa.Integer(), nullable=False),
        sa.Column("successful_explorations", sa.Integer(), nullable=False),
        sa.Column("failed_explorations", sa.Integer(), nullable=False),
        sa.Column("hero_influence", sa.Integer(), nullable=False),
        sa.Column("villain_influence", sa.Integer(), nullable=False),
        sa.Column("discoveries_found", sa.Integer(), nullable=False),
        sa.Column("last_exploration_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("discord_user_id", "guild_id", name="uq_player_user_guild"),
    )
    op.create_index("ix_players_guild_xp", "players", ["guild_id", "experience"])
    op.create_table(
        "weekly_objectives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("objective_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_value", sa.Integer(), nullable=False),
        sa.Column("progress_value", sa.Integer(), nullable=False),
        sa.Column("reward_gold", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("rewards_granted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_weekly_guild_active", "weekly_objectives", ["guild_id", "resolved_at"])
    op.create_table(
        "exploration_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resolution_key", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("encounter_key", sa.String(length=120), nullable=False),
        sa.Column("selected_choice_key", sa.String(length=120)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resolution_key", name="uq_exploration_resolution_key"),
    )
    op.create_index(
        "ix_exploration_active_player", "exploration_sessions", ["player_id", "resolved_at", "expires_at"]
    )
    op.create_table(
        "player_discoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("discovery_id", sa.Integer(), sa.ForeignKey("discoveries.id"), nullable=False),
        sa.Column("times_found", sa.Integer(), nullable=False),
        sa.Column("first_found_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_found_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("player_id", "discovery_id", name="uq_player_discovery"),
    )
    op.create_table(
        "encounter_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exploration_session_id", sa.Integer(), sa.ForeignKey("exploration_sessions.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("encounter_key", sa.String(length=120), nullable=False),
        sa.Column("choice_key", sa.String(length=120), nullable=False),
        sa.Column("gold_awarded", sa.Integer(), nullable=False),
        sa.Column("experience_awarded", sa.Integer(), nullable=False),
        sa.Column("discovery_key", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exploration_session_id", name="uq_history_session"),
    )
    op.create_table(
        "weekly_player_contributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weekly_objective_id", sa.Integer(), sa.ForeignKey("weekly_objectives.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("contribution_value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("weekly_objective_id", "player_id", name="uq_weekly_player"),
    )
    op.create_index(
        "ix_weekly_contribution_value",
        "weekly_player_contributions",
        ["weekly_objective_id", "contribution_value"],
    )


def downgrade() -> None:
    op.drop_index("ix_weekly_contribution_value", table_name="weekly_player_contributions")
    op.drop_table("weekly_player_contributions")
    op.drop_table("encounter_history")
    op.drop_table("player_discoveries")
    op.drop_index("ix_exploration_active_player", table_name="exploration_sessions")
    op.drop_table("exploration_sessions")
    op.drop_index("ix_weekly_guild_active", table_name="weekly_objectives")
    op.drop_table("weekly_objectives")
    op.drop_index("ix_players_guild_xp", table_name="players")
    op.drop_table("players")
    op.drop_index("ix_guild_dungeons_discord_guild_id", table_name="guild_dungeons")
    op.drop_table("guild_dungeons")
    op.drop_table("discoveries")
