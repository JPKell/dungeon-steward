from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base, TimestampMixin


class ContentDungeonLevel(TimestampMixin, Base):
    __tablename__ = "content_dungeon_levels"
    __table_args__ = (
        UniqueConstraint("level", name="uq_content_dungeon_levels_level"),
        Index("ix_content_dungeon_levels_required", "required_explore_level", "required_combat_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    enemy_level_min: Mapped[int] = mapped_column(Integer, nullable=False)
    enemy_level_max: Mapped[int] = mapped_column(Integer, nullable=False)
    stat_modifier: Mapped[float] = mapped_column(Float, nullable=False)
    reward_modifier: Mapped[float] = mapped_column(Float, nullable=False)
    target_day: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_gold_modifier: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_xp_modifier: Mapped[float] = mapped_column(Float, nullable=False)
    expected_player_power: Mapped[float] = mapped_column(Float, nullable=False)
    required_explore_level: Mapped[int] = mapped_column(Integer, nullable=False)
    required_combat_level: Mapped[int] = mapped_column(Integer, nullable=False)
    required_equipment_power: Mapped[float] = mapped_column(Float, nullable=False)
    required_discoveries: Mapped[int] = mapped_column(Integer, nullable=False)
    required_defense_wins: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_previous_completion: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentEnemy(TimestampMixin, Base):
    __tablename__ = "content_enemies"
    __table_args__ = (
        UniqueConstraint("key", name="uq_content_enemies_key"),
        Index("ix_content_enemies_dungeon_range", "min_dungeon_level", "max_dungeon_level"),
        Index("ix_content_enemies_enabled_rank", "enabled", "rank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    min_dungeon_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_dungeon_level: Mapped[int] = mapped_column(Integer, nullable=False)
    base_hp_min: Mapped[int] = mapped_column(Integer, nullable=False)
    base_hp_max: Mapped[int] = mapped_column(Integer, nullable=False)
    base_attack_min: Mapped[int] = mapped_column(Integer, nullable=False)
    base_attack_max: Mapped[int] = mapped_column(Integer, nullable=False)
    base_defense_min: Mapped[int] = mapped_column(Integer, nullable=False)
    base_defense_max: Mapped[int] = mapped_column(Integer, nullable=False)
    base_speed_min: Mapped[int] = mapped_column(Integer, nullable=False)
    base_speed_max: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_modifier_min: Mapped[float] = mapped_column(Float, nullable=False)
    stage_modifier_max: Mapped[float] = mapped_column(Float, nullable=False)
    gold_min: Mapped[int] = mapped_column(Integer, nullable=False)
    gold_max: Mapped[int] = mapped_column(Integer, nullable=False)
    xp_min: Mapped[int] = mapped_column(Integer, nullable=False)
    xp_max: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rank: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentEquipmentItem(TimestampMixin, Base):
    __tablename__ = "content_equipment_items"
    __table_args__ = (
        UniqueConstraint("key", name="uq_content_equipment_items_key"),
        Index("ix_content_equipment_items_slot_rarity", "slot", "rarity"),
        Index("ix_content_equipment_items_level_range", "min_level", "max_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slot: Mapped[str] = mapped_column(String(40), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    attack: Mapped[int] = mapped_column(Integer, nullable=False)
    defense: Mapped[int] = mapped_column(Integer, nullable=False)
    speed: Mapped[int] = mapped_column(Integer, nullable=False)
    thumbnail_asset: Mapped[str | None] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentEquipmentDescription(TimestampMixin, Base):
    __tablename__ = "content_equipment_descriptions"
    __table_args__ = (UniqueConstraint("equipment_key", name="uq_content_equipment_descriptions_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    equipment_key: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class ContentEncounter(TimestampMixin, Base):
    __tablename__ = "content_encounters"
    __table_args__ = (
        UniqueConstraint("key", name="uq_content_encounters_key"),
        Index("ix_content_encounters_enabled_level", "enabled", "min_level"),
        Index("ix_content_encounters_category_rarity", "category", "rarity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    choices: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentDiscovery(TimestampMixin, Base):
    __tablename__ = "content_discoveries"
    __table_args__ = (
        UniqueConstraint("key", name="uq_content_discoveries_key"),
        Index("ix_content_discoveries_enabled_rarity", "enabled", "rarity"),
        Index("ix_content_discoveries_category", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentPotionDocument(TimestampMixin, Base):
    __tablename__ = "content_potion_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    balance_intent: Mapped[str] = mapped_column(Text, nullable=False)
    drop_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    activation_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentPotionItem(TimestampMixin, Base):
    __tablename__ = "content_potion_items"
    __table_args__ = (
        UniqueConstraint("key", name="uq_content_potion_items_key"),
        Index("ix_content_potion_items_group_tier", "effect_group", "tier"),
        Index("ix_content_potion_items_level_range", "min_explore_level", "max_explore_level"),
        Index("ix_content_potion_items_enabled_rarity", "enabled", "rarity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    potion_type: Mapped[str] = mapped_column(String(80), nullable=False)
    effect_group: Mapped[str] = mapped_column(String(40), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    icon_key: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    min_explore_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_explore_level: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_drop_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    inventory_stack_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    consumable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sort_order_value: Mapped[int] = mapped_column("sort_order_content", Integer, nullable=False)
    effect: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    thumbnail_asset: Mapped[str | None] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentProgressionDocument(TimestampMixin, Base):
    __tablename__ = "content_progression_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    new_player: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    combat_leveling: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    defense: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enemy_generation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    shop: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentLocation(TimestampMixin, Base):
    __tablename__ = "content_locations"
    __table_args__ = (UniqueConstraint("key", name="uq_content_locations_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    banner_asset: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentImageAssetDocument(TimestampMixin, Base):
    __tablename__ = "content_image_asset_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentImageAsset(TimestampMixin, Base):
    __tablename__ = "content_image_assets"
    __table_args__ = (
        UniqueConstraint("asset_key", name="uq_content_image_assets_key"),
        Index("ix_content_image_assets_type_required", "type", "required"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_key: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    alt_text: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentImageAssetRegistryDocument(TimestampMixin, Base):
    __tablename__ = "content_image_asset_registry_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentImageAssetRegistryEntry(TimestampMixin, Base):
    __tablename__ = "content_image_asset_registry_entries"
    __table_args__ = (UniqueConstraint("asset_key", name="uq_content_image_asset_registry_entries_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_key: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str | None] = mapped_column(String(80))
    filename: Mapped[str | None] = mapped_column(String(240))
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    channel_id: Mapped[str | None] = mapped_column(String(80))
    message_id: Mapped[str | None] = mapped_column(String(80))
    attachment_id: Mapped[str | None] = mapped_column(String(80))
    cdn_url: Mapped[str | None] = mapped_column(String(1000))
    uploaded_at: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentValidationReport(TimestampMixin, Base):
    __tablename__ = "content_validation_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    errors: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    potions_by_group: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    equipment_by_slot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    equipment_by_rarity: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    equipment_valid_options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    shop_rarity_percentages: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_coverage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ContentSimulationResult(TimestampMixin, Base):
    __tablename__ = "content_simulation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    shop_rarity_percentages: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profiles: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_evaluation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
