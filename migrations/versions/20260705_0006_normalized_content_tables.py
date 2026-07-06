"""Normalize gameplay content tables.

Revision ID: 20260705_0006
Revises: 20260705_0005
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260705_0006"
down_revision = "20260705_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_encounter_choices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=False),
        sa.Column("gold_min", sa.Integer(), nullable=False),
        sa.Column("gold_max", sa.Integer(), nullable=False),
        sa.Column("xp_min", sa.Integer(), nullable=False),
        sa.Column("xp_max", sa.Integer(), nullable=False),
        sa.Column("hero_effect", sa.Integer(), nullable=False),
        sa.Column("villain_effect", sa.Integer(), nullable=False),
        sa.Column("stability_effect", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("discovery_key", sa.String(length=160)),
        sa.Column("weekly_progress", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["encounter_id"], ["content_encounters.id"]),
        sa.UniqueConstraint("encounter_id", "key", name="uq_content_encounter_choices_encounter_key"),
    )
    op.create_index(
        "ix_content_encounter_choices_encounter",
        "content_encounter_choices",
        ["encounter_id", "sort_order"],
    )

    op.create_table(
        "content_potion_rarity_bonuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("rarity", sa.String(length=40), nullable=False),
        sa.Column("bonus", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["content_potion_documents.id"]),
        sa.UniqueConstraint("document_id", "rarity", name="uq_content_potion_rarity_bonus"),
    )

    op.create_table(
        "content_potion_effect_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("potion_item_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["potion_item_id"], ["content_potion_items.id"]),
        sa.UniqueConstraint(
            "potion_item_id",
            "target",
            name="uq_content_potion_effect_targets_item_target",
        ),
    )
    op.create_index(
        "ix_content_potion_effect_targets_item",
        "content_potion_effect_targets",
        ["potion_item_id", "sort_order"],
    )

    with op.batch_alter_table("content_potion_documents") as batch:
        batch.add_column(sa.Column("drop_eligibility_stat", sa.String(length=80), nullable=False, server_default=""))
        batch.add_column(sa.Column("base_drop_chance", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("successful_choice_bonus", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("failed_choice_multiplier", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column(
                "dungeon_level_bonus_per_level_after_one",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("maximum_drop_chance", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_drops_per_exploration", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("drop_selection_method", sa.String(length=120), nullable=False, server_default=""))
        batch.add_column(sa.Column("drop_item_weight_field", sa.String(length=120), nullable=False, server_default=""))
        batch.add_column(sa.Column("drop_award_timing", sa.String(length=120), nullable=False, server_default=""))
        batch.add_column(sa.Column("activation_clock", sa.String(length=80), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("duration_runs_while_offline", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("max_simultaneous_effect_groups", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("same_effect_group_policy", sa.String(length=120), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("replacement_requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("effects_are_not_retroactive", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("active_at_boundary_rule", sa.String(length=160), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("healing_occurs_after_victory_only", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column(
                "xp_potions_affect_defense_combat_xp_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "luck_affects_enemy_gold_and_combat_xp",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.drop_column("drop_rules")
        batch.drop_column("activation_rules")
        batch.drop_column("payload")

    with op.batch_alter_table("content_potion_items") as batch:
        batch.add_column(sa.Column("effect_kind", sa.String(length=80), nullable=False, server_default=""))
        batch.add_column(sa.Column("effect_operation", sa.String(length=80), nullable=False, server_default=""))
        batch.add_column(sa.Column("effect_bonus", sa.Float()))
        batch.add_column(sa.Column("effect_final_multiplier", sa.Float()))
        batch.add_column(sa.Column("effect_chance", sa.Float()))
        batch.add_column(sa.Column("effect_max_hp_percent", sa.Float()))
        batch.add_column(sa.Column("effect_flat_cap", sa.Integer()))
        batch.add_column(sa.Column("effect_minimum_heal", sa.Integer()))
        batch.add_column(sa.Column("effect_heals_on_activation", sa.Boolean()))
        batch.add_column(sa.Column("effect_trigger", sa.String(length=120)))
        batch.add_column(sa.Column("effect_proc_scope", sa.String(length=120)))
        batch.drop_column("effect")
        batch.drop_column("payload")

    for table_name in (
        "content_dungeon_levels",
        "content_enemies",
        "content_equipment_items",
        "content_discoveries",
        "content_progression_documents",
        "content_locations",
        "content_image_asset_documents",
        "content_image_assets",
        "content_image_asset_registry_documents",
        "content_image_asset_registry_entries",
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("payload")

    with op.batch_alter_table("content_encounters") as batch:
        batch.drop_column("choices")
        batch.drop_column("payload")


def downgrade() -> None:
    with op.batch_alter_table("content_encounters") as batch:
        batch.add_column(sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("choices", sa.JSON(), nullable=False, server_default="[]"))

    for table_name in (
        "content_image_asset_registry_entries",
        "content_image_asset_registry_documents",
        "content_image_assets",
        "content_image_asset_documents",
        "content_locations",
        "content_progression_documents",
        "content_discoveries",
        "content_equipment_items",
        "content_enemies",
        "content_dungeon_levels",
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))

    with op.batch_alter_table("content_potion_items") as batch:
        batch.add_column(sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("effect", sa.JSON(), nullable=False, server_default="{}"))
        batch.drop_column("effect_proc_scope")
        batch.drop_column("effect_trigger")
        batch.drop_column("effect_heals_on_activation")
        batch.drop_column("effect_minimum_heal")
        batch.drop_column("effect_flat_cap")
        batch.drop_column("effect_max_hp_percent")
        batch.drop_column("effect_chance")
        batch.drop_column("effect_final_multiplier")
        batch.drop_column("effect_bonus")
        batch.drop_column("effect_operation")
        batch.drop_column("effect_kind")

    with op.batch_alter_table("content_potion_documents") as batch:
        batch.add_column(sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("activation_rules", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("drop_rules", sa.JSON(), nullable=False, server_default="{}"))
        batch.drop_column("luck_affects_enemy_gold_and_combat_xp")
        batch.drop_column("xp_potions_affect_defense_combat_xp_only")
        batch.drop_column("healing_occurs_after_victory_only")
        batch.drop_column("active_at_boundary_rule")
        batch.drop_column("effects_are_not_retroactive")
        batch.drop_column("replacement_requires_confirmation")
        batch.drop_column("same_effect_group_policy")
        batch.drop_column("max_simultaneous_effect_groups")
        batch.drop_column("duration_runs_while_offline")
        batch.drop_column("activation_clock")
        batch.drop_column("drop_award_timing")
        batch.drop_column("drop_item_weight_field")
        batch.drop_column("drop_selection_method")
        batch.drop_column("max_drops_per_exploration")
        batch.drop_column("maximum_drop_chance")
        batch.drop_column("dungeon_level_bonus_per_level_after_one")
        batch.drop_column("failed_choice_multiplier")
        batch.drop_column("successful_choice_bonus")
        batch.drop_column("base_drop_chance")
        batch.drop_column("drop_eligibility_stat")

    op.drop_index("ix_content_potion_effect_targets_item", table_name="content_potion_effect_targets")
    op.drop_table("content_potion_effect_targets")
    op.drop_table("content_potion_rarity_bonuses")
    op.drop_index("ix_content_encounter_choices_encounter", table_name="content_encounter_choices")
    op.drop_table("content_encounter_choices")
