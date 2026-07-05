"""Add database-backed content tables.

Revision ID: 20260705_0005
Revises: 20260703_0004
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260705_0005"
down_revision = "20260703_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_dungeon_levels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("enemy_level_min", sa.Integer(), nullable=False),
        sa.Column("enemy_level_max", sa.Integer(), nullable=False),
        sa.Column("stat_modifier", sa.Float(), nullable=False),
        sa.Column("reward_modifier", sa.Float(), nullable=False),
        sa.Column("target_day", sa.Integer(), nullable=False),
        sa.Column("exploration_gold_modifier", sa.Float(), nullable=False),
        sa.Column("exploration_xp_modifier", sa.Float(), nullable=False),
        sa.Column("expected_player_power", sa.Float(), nullable=False),
        sa.Column("required_explore_level", sa.Integer(), nullable=False),
        sa.Column("required_combat_level", sa.Integer(), nullable=False),
        sa.Column("required_equipment_power", sa.Float(), nullable=False),
        sa.Column("required_discoveries", sa.Integer(), nullable=False),
        sa.Column("required_defense_wins", sa.Integer(), nullable=False),
        sa.Column("requires_previous_completion", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("level", name="uq_content_dungeon_levels_level"),
    )
    op.create_index(
        "ix_content_dungeon_levels_required",
        "content_dungeon_levels",
        ["required_explore_level", "required_combat_level"],
    )

    op.create_table(
        "content_enemies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("min_dungeon_level", sa.Integer(), nullable=False),
        sa.Column("max_dungeon_level", sa.Integer(), nullable=False),
        sa.Column("base_hp_min", sa.Integer(), nullable=False),
        sa.Column("base_hp_max", sa.Integer(), nullable=False),
        sa.Column("base_attack_min", sa.Integer(), nullable=False),
        sa.Column("base_attack_max", sa.Integer(), nullable=False),
        sa.Column("base_defense_min", sa.Integer(), nullable=False),
        sa.Column("base_defense_max", sa.Integer(), nullable=False),
        sa.Column("base_speed_min", sa.Integer(), nullable=False),
        sa.Column("base_speed_max", sa.Integer(), nullable=False),
        sa.Column("stage_modifier_min", sa.Float(), nullable=False),
        sa.Column("stage_modifier_max", sa.Float(), nullable=False),
        sa.Column("gold_min", sa.Integer(), nullable=False),
        sa.Column("gold_max", sa.Integer(), nullable=False),
        sa.Column("xp_min", sa.Integer(), nullable=False),
        sa.Column("xp_max", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_content_enemies_key"),
    )
    op.create_index(
        "ix_content_enemies_dungeon_range",
        "content_enemies",
        ["min_dungeon_level", "max_dungeon_level"],
    )
    op.create_index("ix_content_enemies_enabled_rank", "content_enemies", ["enabled", "rank"])

    op.create_table(
        "content_equipment_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slot", sa.String(length=40), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.Column("max_level", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("hp", sa.Integer(), nullable=False),
        sa.Column("attack", sa.Integer(), nullable=False),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("thumbnail_asset", sa.String(length=160)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_content_equipment_items_key"),
    )
    op.create_index("ix_content_equipment_items_slot_rarity", "content_equipment_items", ["slot", "rarity"])
    op.create_index(
        "ix_content_equipment_items_level_range",
        "content_equipment_items",
        ["min_level", "max_level"],
    )

    op.create_table(
        "content_equipment_descriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("equipment_key", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("equipment_key", name="uq_content_equipment_descriptions_key"),
    )

    op.create_table(
        "content_encounters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_content_encounters_key"),
    )
    op.create_index("ix_content_encounters_enabled_level", "content_encounters", ["enabled", "min_level"])
    op.create_index("ix_content_encounters_category_rarity", "content_encounters", ["category", "rarity"])

    op.create_table(
        "content_discoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("image_url", sa.String(length=500)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_content_discoveries_key"),
    )
    op.create_index("ix_content_discoveries_enabled_rarity", "content_discoveries", ["enabled", "rarity"])
    op.create_index("ix_content_discoveries_category", "content_discoveries", ["category"])

    op.create_table(
        "content_potion_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("balance_intent", sa.Text(), nullable=False),
        sa.Column("drop_rules", sa.JSON(), nullable=False),
        sa.Column("activation_rules", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "content_potion_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("potion_type", sa.String(length=80), nullable=False),
        sa.Column("effect_group", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon_key", sa.String(length=80), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("min_explore_level", sa.Integer(), nullable=False),
        sa.Column("max_explore_level", sa.Integer(), nullable=False),
        sa.Column("exploration_drop_weight", sa.Integer(), nullable=False),
        sa.Column("inventory_stack_limit", sa.Integer(), nullable=False),
        sa.Column("consumable", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order_content", sa.Integer(), nullable=False),
        sa.Column("effect", sa.JSON(), nullable=False),
        sa.Column("thumbnail_asset", sa.String(length=160)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_content_potion_items_key"),
    )
    op.create_index("ix_content_potion_items_group_tier", "content_potion_items", ["effect_group", "tier"])
    op.create_index(
        "ix_content_potion_items_level_range",
        "content_potion_items",
        ["min_explore_level", "max_explore_level"],
    )
    op.create_index("ix_content_potion_items_enabled_rarity", "content_potion_items", ["enabled", "rarity"])

    op.create_table(
        "content_progression_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("exploration", sa.JSON(), nullable=False),
        sa.Column("new_player", sa.JSON(), nullable=False),
        sa.Column("combat_leveling", sa.JSON(), nullable=False),
        sa.Column("defense", sa.JSON(), nullable=False),
        sa.Column("enemy_generation", sa.JSON(), nullable=False),
        sa.Column("shop", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "content_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("banner_asset", sa.String(length=160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_content_locations_key"),
    )

    op.create_table(
        "content_image_asset_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "content_image_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("asset_key", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("alt_text", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.String(length=500)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_key", name="uq_content_image_assets_key"),
    )
    op.create_index(
        "ix_content_image_assets_type_required",
        "content_image_assets",
        ["type", "required"],
    )

    op.create_table(
        "content_image_asset_registry_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "content_image_asset_registry_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("asset_key", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=80)),
        sa.Column("filename", sa.String(length=240)),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("channel_id", sa.String(length=80)),
        sa.Column("message_id", sa.String(length=80)),
        sa.Column("attachment_id", sa.String(length=80)),
        sa.Column("cdn_url", sa.String(length=1000)),
        sa.Column("uploaded_at", sa.String(length=80)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_key", name="uq_content_image_asset_registry_entries_key"),
    )

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


def downgrade() -> None:
    op.drop_table("content_simulation_results")
    op.drop_table("content_validation_reports")
    op.drop_table("content_image_asset_registry_entries")
    op.drop_table("content_image_asset_registry_documents")
    op.drop_index("ix_content_image_assets_type_required", table_name="content_image_assets")
    op.drop_table("content_image_assets")
    op.drop_table("content_image_asset_documents")
    op.drop_table("content_locations")
    op.drop_table("content_progression_documents")
    op.drop_index("ix_content_potion_items_enabled_rarity", table_name="content_potion_items")
    op.drop_index("ix_content_potion_items_level_range", table_name="content_potion_items")
    op.drop_index("ix_content_potion_items_group_tier", table_name="content_potion_items")
    op.drop_table("content_potion_items")
    op.drop_table("content_potion_documents")
    op.drop_index("ix_content_discoveries_category", table_name="content_discoveries")
    op.drop_index("ix_content_discoveries_enabled_rarity", table_name="content_discoveries")
    op.drop_table("content_discoveries")
    op.drop_index("ix_content_encounters_category_rarity", table_name="content_encounters")
    op.drop_index("ix_content_encounters_enabled_level", table_name="content_encounters")
    op.drop_table("content_encounters")
    op.drop_table("content_equipment_descriptions")
    op.drop_index("ix_content_equipment_items_level_range", table_name="content_equipment_items")
    op.drop_index("ix_content_equipment_items_slot_rarity", table_name="content_equipment_items")
    op.drop_table("content_equipment_items")
    op.drop_index("ix_content_enemies_enabled_rank", table_name="content_enemies")
    op.drop_index("ix_content_enemies_dungeon_range", table_name="content_enemies")
    op.drop_table("content_enemies")
    op.drop_index("ix_content_dungeon_levels_required", table_name="content_dungeon_levels")
    op.drop_table("content_dungeon_levels")
