from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    thumbnail_asset: Mapped[str | None] = mapped_column(String(160))


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
    thumbnail_asset: Mapped[str | None] = mapped_column(String(160))
    emoji_asset: Mapped[str | None] = mapped_column(String(160))


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
    subtype: Mapped[str] = mapped_column(String(40), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    attack: Mapped[int] = mapped_column(Integer, nullable=False)
    defense: Mapped[int] = mapped_column(Integer, nullable=False)
    speed: Mapped[int] = mapped_column(Integer, nullable=False)
    thumbnail_asset: Mapped[str | None] = mapped_column(String(160))


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
    choices: Mapped[list[ContentEncounterChoice]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        order_by="ContentEncounterChoice.sort_order",
    )


class ContentEncounterChoice(TimestampMixin, Base):
    __tablename__ = "content_encounter_choices"
    __table_args__ = (
        UniqueConstraint("encounter_id", "key", name="uq_content_encounter_choices_encounter_key"),
        Index("ix_content_encounter_choices_encounter", "encounter_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("content_encounters.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    result_text: Mapped[str] = mapped_column(Text, nullable=False)
    gold_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gold_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    xp_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    xp_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hero_effect: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    villain_effect: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stability_effect: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovery_key: Mapped[str | None] = mapped_column(String(160))
    weekly_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    encounter: Mapped[ContentEncounter] = relationship(back_populates="choices")


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


class ContentPotionDocument(TimestampMixin, Base):
    __tablename__ = "content_potion_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    balance_intent: Mapped[str] = mapped_column(Text, nullable=False)
    drop_eligibility_stat: Mapped[str] = mapped_column(String(80), nullable=False)
    base_drop_chance: Mapped[float] = mapped_column(Float, nullable=False)
    successful_choice_bonus: Mapped[float] = mapped_column(Float, nullable=False)
    failed_choice_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    dungeon_level_bonus_per_level_after_one: Mapped[float] = mapped_column(Float, nullable=False)
    maximum_drop_chance: Mapped[float] = mapped_column(Float, nullable=False)
    max_drops_per_exploration: Mapped[int] = mapped_column(Integer, nullable=False)
    drop_selection_method: Mapped[str] = mapped_column(String(120), nullable=False)
    drop_item_weight_field: Mapped[str] = mapped_column(String(120), nullable=False)
    drop_award_timing: Mapped[str] = mapped_column(String(120), nullable=False)
    activation_clock: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_runs_while_offline: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_simultaneous_effect_groups: Mapped[int] = mapped_column(Integer, nullable=False)
    same_effect_group_policy: Mapped[str] = mapped_column(String(120), nullable=False)
    replacement_requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effects_are_not_retroactive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    active_at_boundary_rule: Mapped[str] = mapped_column(String(160), nullable=False)
    healing_occurs_after_victory_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    xp_potions_affect_defense_combat_xp_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    luck_affects_enemy_gold_and_combat_xp: Mapped[bool] = mapped_column(Boolean, nullable=False)
    encounter_rarity_bonuses: Mapped[list[ContentPotionRarityBonus]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ContentPotionRarityBonus.rarity",
    )


class ContentPotionRarityBonus(TimestampMixin, Base):
    __tablename__ = "content_potion_rarity_bonuses"
    __table_args__ = (UniqueConstraint("document_id", "rarity", name="uq_content_potion_rarity_bonus"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("content_potion_documents.id"), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    bonus: Mapped[float] = mapped_column(Float, nullable=False)

    document: Mapped[ContentPotionDocument] = relationship(back_populates="encounter_rarity_bonuses")


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
    effect_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    effect_operation: Mapped[str] = mapped_column(String(80), nullable=False)
    effect_bonus: Mapped[float | None] = mapped_column(Float)
    effect_final_multiplier: Mapped[float | None] = mapped_column(Float)
    effect_chance: Mapped[float | None] = mapped_column(Float)
    effect_max_hp_percent: Mapped[float | None] = mapped_column(Float)
    effect_flat_cap: Mapped[int | None] = mapped_column(Integer)
    effect_minimum_heal: Mapped[int | None] = mapped_column(Integer)
    effect_heals_on_activation: Mapped[bool | None] = mapped_column(Boolean)
    effect_trigger: Mapped[str | None] = mapped_column(String(120))
    effect_proc_scope: Mapped[str | None] = mapped_column(String(120))
    thumbnail_asset: Mapped[str | None] = mapped_column(String(160))
    effect_targets: Mapped[list[ContentPotionEffectTarget]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ContentPotionEffectTarget.sort_order",
    )


class ContentPotionEffectTarget(TimestampMixin, Base):
    __tablename__ = "content_potion_effect_targets"
    __table_args__ = (
        UniqueConstraint("potion_item_id", "target", name="uq_content_potion_effect_targets_item_target"),
        Index("ix_content_potion_effect_targets_item", "potion_item_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    potion_item_id: Mapped[int] = mapped_column(ForeignKey("content_potion_items.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target: Mapped[str] = mapped_column(String(120), nullable=False)

    item: Mapped[ContentPotionItem] = relationship(back_populates="effect_targets")


class ContentProgressionDocument(TimestampMixin, Base):
    __tablename__ = "content_progression_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_base_cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_min_cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_cooldown_reduction_per_level: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_cooldown_cap_level: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_dungeon_gold_growth: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_dungeon_xp_growth: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_post_cap_gold_growth: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_underpowered_reward_floor: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_risk_gold_bonus: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_failure_xp_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    new_player_base_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    new_player_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    new_player_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    new_player_speed: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_hp_milestone_interval: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_hp_milestone_bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_stat_milestone_interval: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_stat_milestone_bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    defense_base_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    defense_max_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    defense_duration_cap_level: Mapped[int] = mapped_column(Integer, nullable=False)
    defense_restore_full_hp_on_start: Mapped[bool] = mapped_column(Boolean, nullable=False)
    defense_post_defeat_hp_percent: Mapped[float] = mapped_column(Float, nullable=False)
    defense_minimum_damage: Mapped[int] = mapped_column(Integer, nullable=False)
    defense_max_battle_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    defense_maximum_elapsed_days: Mapped[int] = mapped_column(Integer, nullable=False)
    enemy_generation_level_stat_scale: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_level_reward_scale: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_power_xp_floor: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_power_xp_ceiling: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_trivial_enemy_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_trivial_enemy_xp_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_combat_gold_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    enemy_generation_trivial_enemy_gold_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    shop_stock_size: Mapped[int] = mapped_column(Integer, nullable=False)

    curves: Mapped[list[ContentProgressionCurve]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ContentProgressionCurve.key",
    )
    rarity_multipliers: Mapped[list[ContentProgressionRarityMultiplier]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ContentProgressionRarityMultiplier.id",
    )
    shop_rarity_weights: Mapped[list[ContentProgressionShopRarityWeight]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ContentProgressionShopRarityWeight.rarity",
    )
    shop_rarity_bands: Mapped[list[ContentProgressionShopRarityBand]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ContentProgressionShopRarityBand.sort_order",
    )


class ContentProgressionCurve(TimestampMixin, Base):
    __tablename__ = "content_progression_curves"
    __table_args__ = (
        UniqueConstraint("document_id", "key", name="uq_content_progression_curves_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("content_progression_documents.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    curve: Mapped[str] = mapped_column(String(40), nullable=False)
    base: Mapped[float] = mapped_column(Float, nullable=False)
    linear_growth: Mapped[float] = mapped_column(Float, nullable=False)
    quadratic_growth: Mapped[float] = mapped_column(Float, nullable=False)
    exponential_growth: Mapped[float] = mapped_column(Float, nullable=False)
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    max_level: Mapped[int | None] = mapped_column(Integer)

    document: Mapped[ContentProgressionDocument] = relationship(back_populates="curves")


class ContentProgressionRarityMultiplier(TimestampMixin, Base):
    __tablename__ = "content_progression_rarity_multipliers"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "reward_type",
            "rarity",
            name="uq_content_progression_rarity_multiplier",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("content_progression_documents.id"), nullable=False)
    reward_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)

    document: Mapped[ContentProgressionDocument] = relationship(back_populates="rarity_multipliers")


class ContentProgressionShopRarityWeight(TimestampMixin, Base):
    __tablename__ = "content_progression_shop_rarity_weights"
    __table_args__ = (
        UniqueConstraint("document_id", "rarity", name="uq_content_progression_shop_rarity_weight"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("content_progression_documents.id"), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[ContentProgressionDocument] = relationship(back_populates="shop_rarity_weights")


class ContentProgressionShopRarityBand(TimestampMixin, Base):
    __tablename__ = "content_progression_shop_rarity_bands"
    __table_args__ = (
        UniqueConstraint("document_id", "min_level", name="uq_content_progression_shop_rarity_band_level"),
        Index("ix_content_progression_shop_rarity_bands_document", "document_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("content_progression_documents.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[ContentProgressionDocument] = relationship(back_populates="shop_rarity_bands")
    weights: Mapped[list[ContentProgressionShopRarityBandWeight]] = relationship(
        back_populates="band",
        cascade="all, delete-orphan",
        order_by="ContentProgressionShopRarityBandWeight.rarity",
    )


class ContentProgressionShopRarityBandWeight(TimestampMixin, Base):
    __tablename__ = "content_progression_shop_rarity_band_weights"
    __table_args__ = (
        UniqueConstraint("band_id", "rarity", name="uq_content_progression_shop_rarity_band_weight"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    band_id: Mapped[int] = mapped_column(ForeignKey("content_progression_shop_rarity_bands.id"), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)

    band: Mapped[ContentProgressionShopRarityBand] = relationship(back_populates="weights")


class ContentLocation(TimestampMixin, Base):
    __tablename__ = "content_locations"
    __table_args__ = (UniqueConstraint("key", name="uq_content_locations_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    banner_asset: Mapped[str] = mapped_column(String(160), nullable=False)


class ContentImageAssetDocument(TimestampMixin, Base):
    __tablename__ = "content_image_asset_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


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


class ContentImageAssetRegistryDocument(TimestampMixin, Base):
    __tablename__ = "content_image_asset_registry_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


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
