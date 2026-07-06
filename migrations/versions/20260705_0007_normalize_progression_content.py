"""Normalize progression content and remove generated report tables.

Revision ID: 20260705_0007
Revises: 20260705_0006
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260705_0007"
down_revision = "20260705_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_progression_curves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("curve", sa.String(length=40), nullable=False),
        sa.Column("base", sa.Float(), nullable=False),
        sa.Column("linear_growth", sa.Float(), nullable=False),
        sa.Column("quadratic_growth", sa.Float(), nullable=False),
        sa.Column("exponential_growth", sa.Float(), nullable=False),
        sa.Column("minimum", sa.Float()),
        sa.Column("maximum", sa.Float()),
        sa.Column("max_level", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["content_progression_documents.id"]),
        sa.UniqueConstraint("document_id", "key", name="uq_content_progression_curves_key"),
    )
    op.create_table(
        "content_progression_rarity_multipliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("reward_type", sa.String(length=20), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("multiplier", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["content_progression_documents.id"]),
        sa.UniqueConstraint(
            "document_id",
            "reward_type",
            "rarity",
            name="uq_content_progression_rarity_multiplier",
        ),
    )
    op.create_table(
        "content_progression_shop_rarity_weights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["content_progression_documents.id"]),
        sa.UniqueConstraint("document_id", "rarity", name="uq_content_progression_shop_rarity_weight"),
    )
    op.create_table(
        "content_progression_shop_rarity_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["content_progression_documents.id"]),
        sa.UniqueConstraint(
            "document_id",
            "min_level",
            name="uq_content_progression_shop_rarity_band_level",
        ),
    )
    op.create_index(
        "ix_content_progression_shop_rarity_bands_document",
        "content_progression_shop_rarity_bands",
        ["document_id", "sort_order"],
    )
    op.create_table(
        "content_progression_shop_rarity_band_weights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("band_id", sa.Integer(), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["band_id"], ["content_progression_shop_rarity_bands.id"]),
        sa.UniqueConstraint("band_id", "rarity", name="uq_content_progression_shop_rarity_band_weight"),
    )

    with op.batch_alter_table("content_progression_documents") as batch:
        batch.add_column(sa.Column("exploration_base_cooldown_minutes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("exploration_min_cooldown_minutes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("exploration_cooldown_reduction_per_level", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("exploration_cooldown_cap_level", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("exploration_dungeon_gold_growth", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("exploration_dungeon_xp_growth", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("exploration_post_cap_gold_growth", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("exploration_underpowered_reward_floor", sa.Float(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("exploration_risk_gold_bonus", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("exploration_failure_xp_multiplier", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("new_player_base_hp", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("new_player_attack", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("new_player_defense", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("new_player_speed", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("combat_hp_milestone_interval", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("combat_hp_milestone_bonus", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("combat_stat_milestone_interval", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("combat_stat_milestone_bonus", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("defense_base_minutes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("defense_max_minutes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("defense_duration_cap_level", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("defense_restore_full_hp_on_start", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("defense_post_defeat_hp_percent", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("defense_minimum_damage", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("defense_max_battle_rounds", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("defense_maximum_elapsed_days", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("enemy_generation_level_stat_scale", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("enemy_generation_level_reward_scale", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("enemy_generation_power_xp_floor", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("enemy_generation_power_xp_ceiling", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("enemy_generation_trivial_enemy_ratio", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("enemy_generation_trivial_enemy_xp_multiplier", sa.Float(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("enemy_generation_combat_gold_multiplier", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("enemy_generation_trivial_enemy_gold_multiplier", sa.Float(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("shop_stock_size", sa.Integer(), nullable=False, server_default="0"))
        batch.drop_column("exploration")
        batch.drop_column("new_player")
        batch.drop_column("combat_leveling")
        batch.drop_column("defense")
        batch.drop_column("enemy_generation")
        batch.drop_column("shop")

    _drop_table_if_exists("content_simulation_results")
    _drop_table_if_exists("content_validation_reports")


def downgrade() -> None:
    _create_report_tables_if_missing()

    with op.batch_alter_table("content_progression_documents") as batch:
        batch.add_column(sa.Column("shop", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("enemy_generation", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("defense", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("combat_leveling", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("new_player", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("exploration", sa.JSON(), nullable=False, server_default="{}"))
        batch.drop_column("shop_stock_size")
        batch.drop_column("enemy_generation_trivial_enemy_gold_multiplier")
        batch.drop_column("enemy_generation_combat_gold_multiplier")
        batch.drop_column("enemy_generation_trivial_enemy_xp_multiplier")
        batch.drop_column("enemy_generation_trivial_enemy_ratio")
        batch.drop_column("enemy_generation_power_xp_ceiling")
        batch.drop_column("enemy_generation_power_xp_floor")
        batch.drop_column("enemy_generation_level_reward_scale")
        batch.drop_column("enemy_generation_level_stat_scale")
        batch.drop_column("defense_maximum_elapsed_days")
        batch.drop_column("defense_max_battle_rounds")
        batch.drop_column("defense_minimum_damage")
        batch.drop_column("defense_post_defeat_hp_percent")
        batch.drop_column("defense_restore_full_hp_on_start")
        batch.drop_column("defense_duration_cap_level")
        batch.drop_column("defense_max_minutes")
        batch.drop_column("defense_base_minutes")
        batch.drop_column("combat_stat_milestone_bonus")
        batch.drop_column("combat_stat_milestone_interval")
        batch.drop_column("combat_hp_milestone_bonus")
        batch.drop_column("combat_hp_milestone_interval")
        batch.drop_column("new_player_speed")
        batch.drop_column("new_player_defense")
        batch.drop_column("new_player_attack")
        batch.drop_column("new_player_base_hp")
        batch.drop_column("exploration_failure_xp_multiplier")
        batch.drop_column("exploration_risk_gold_bonus")
        batch.drop_column("exploration_underpowered_reward_floor")
        batch.drop_column("exploration_post_cap_gold_growth")
        batch.drop_column("exploration_dungeon_xp_growth")
        batch.drop_column("exploration_dungeon_gold_growth")
        batch.drop_column("exploration_cooldown_cap_level")
        batch.drop_column("exploration_cooldown_reduction_per_level")
        batch.drop_column("exploration_min_cooldown_minutes")
        batch.drop_column("exploration_base_cooldown_minutes")

    op.drop_table("content_progression_shop_rarity_band_weights")
    op.drop_index(
        "ix_content_progression_shop_rarity_bands_document",
        table_name="content_progression_shop_rarity_bands",
    )
    op.drop_table("content_progression_shop_rarity_bands")
    op.drop_table("content_progression_shop_rarity_weights")
    op.drop_table("content_progression_rarity_multipliers")
    op.drop_table("content_progression_curves")


def _drop_table_if_exists(table_name: str) -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(table_name):
        op.drop_table(table_name)


def _create_report_tables_if_missing() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("content_validation_reports"):
        op.create_table(
            "content_validation_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("errors", sa.JSON(), nullable=False),
            sa.Column("counts", sa.JSON(), nullable=False),
            sa.Column("potions_by_group", sa.JSON(), nullable=False),
            sa.Column("equipment_by_slot", sa.JSON(), nullable=False),
            sa.Column("equipment_by_rarity", sa.JSON(), nullable=False),
            sa.Column("equipment_valid_options", sa.JSON(), nullable=False),
            sa.Column("shop_rarity_percentages", sa.JSON(), nullable=False),
            sa.Column("content_coverage", sa.JSON(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not inspector.has_table("content_simulation_results"):
        op.create_table(
            "content_simulation_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("assumptions", sa.JSON(), nullable=False),
            sa.Column("shop_rarity_percentages", sa.JSON(), nullable=False),
            sa.Column("profiles", sa.JSON(), nullable=False),
            sa.Column("target_evaluation", sa.JSON(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
