from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from bot.models import (
    ContentDiscovery,
    ContentDungeonLevel,
    ContentEncounter,
    ContentEncounterChoice,
    ContentEnemy,
    ContentEquipmentDescription,
    ContentEquipmentItem,
    ContentImageAsset,
    ContentImageAssetDocument,
    ContentImageAssetRegistryDocument,
    ContentImageAssetRegistryEntry,
    ContentLocation,
    ContentPotionDocument,
    ContentPotionEffectTarget,
    ContentPotionItem,
    ContentPotionRarityBonus,
    ContentProgressionCurve,
    ContentProgressionDocument,
    ContentProgressionRarityMultiplier,
    ContentProgressionShopRarityBand,
    ContentProgressionShopRarityBandWeight,
    ContentProgressionShopRarityWeight,
    Discovery,
)

CONTENT_DIR = Path(__file__).parents[1] / "content"
CONTENT_FILENAMES = (
    "progression.json",
    "dungeon_levels.json",
    "enemies.json",
    "equipment.json",
    "equipment_descriptions.json",
    "encounters.json",
    "discoveries.json",
    "potion_items.json",
    "locations.json",
    "image_assets.json",
    "image_asset_registry.json",
)


class ContentDatabaseError(ValueError):
    pass


@dataclass(frozen=True)
class ContentTransferResult:
    direction: str
    content_dir: Path
    files: tuple[str, ...]
    rows: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "content_dir": str(self.content_dir),
            "files": list(self.files),
            "rows": self.rows,
        }


def load_content_from_files(
    session: Session,
    *,
    content_dir: Path | str = CONTENT_DIR,
    sync_runtime_discoveries: bool = True,
) -> ContentTransferResult:
    content_path = Path(content_dir)
    documents = {filename: _read_json(content_path / filename) for filename in CONTENT_FILENAMES}
    _clear_content_tables(session)

    rows = {
        "progression.json": _load_progression(session, documents["progression.json"]),
        "dungeon_levels.json": _load_dungeon_levels(session, documents["dungeon_levels.json"]),
        "enemies.json": _load_enemies(session, documents["enemies.json"]),
        "equipment.json": _load_equipment(session, documents["equipment.json"]),
        "equipment_descriptions.json": _load_equipment_descriptions(
            session, documents["equipment_descriptions.json"]
        ),
        "encounters.json": _load_encounters(session, documents["encounters.json"]),
        "discoveries.json": _load_discoveries(session, documents["discoveries.json"]),
        "potion_items.json": _load_potions(session, documents["potion_items.json"]),
        "locations.json": _load_locations(session, documents["locations.json"]),
        "image_assets.json": _load_image_assets(session, documents["image_assets.json"]),
        "image_asset_registry.json": _load_image_asset_registry(
            session, documents["image_asset_registry.json"]
        ),
    }
    if sync_runtime_discoveries:
        _sync_runtime_discoveries(session)
    session.flush()
    return ContentTransferResult("load", content_path, CONTENT_FILENAMES, rows)


def dump_content_to_files(
    session: Session,
    *,
    content_dir: Path | str = CONTENT_DIR,
    indent: int = 2,
) -> ContentTransferResult:
    content_path = Path(content_dir)
    content_path.mkdir(parents=True, exist_ok=True)

    documents = {
        "progression.json": _dump_progression(session),
        "dungeon_levels.json": _dump_dungeon_levels(session),
        "enemies.json": _dump_enemies(session),
        "equipment.json": _dump_equipment(session),
        "equipment_descriptions.json": _dump_equipment_descriptions(session),
        "encounters.json": _dump_encounters(session),
        "discoveries.json": _dump_discoveries(session),
        "potion_items.json": _dump_potions(session),
        "locations.json": _dump_locations(session),
        "image_assets.json": _dump_image_assets(session),
        "image_asset_registry.json": _dump_image_asset_registry(session),
    }
    for filename in CONTENT_FILENAMES:
        _write_json(content_path / filename, documents[filename], indent=indent)
    rows = _dump_row_counts(documents)
    return ContentTransferResult("dump", content_path, CONTENT_FILENAMES, rows)


def load_content_documents_from_database(session: Session) -> dict[str, Any]:
    return {
        "progression.json": _dump_progression(session),
        "dungeon_levels.json": _dump_dungeon_levels(session),
        "enemies.json": _dump_enemies(session),
        "equipment.json": _dump_equipment(session),
        "equipment_descriptions.json": _dump_equipment_descriptions(session),
        "encounters.json": _dump_encounters(session),
        "discoveries.json": _dump_discoveries(session),
        "potion_items.json": _dump_potions(session),
        "locations.json": _dump_locations(session),
        "image_assets.json": _dump_image_assets(session),
        "image_asset_registry.json": _dump_image_asset_registry(session),
    }


def sync_runtime_discoveries_from_content_tables(session: Session) -> None:
    _sync_runtime_discoveries(session)


def _clear_content_tables(session: Session) -> None:
    for model in (
        ContentImageAssetRegistryEntry,
        ContentImageAssetRegistryDocument,
        ContentImageAsset,
        ContentImageAssetDocument,
        ContentLocation,
        ContentProgressionShopRarityBandWeight,
        ContentProgressionShopRarityBand,
        ContentProgressionShopRarityWeight,
        ContentProgressionRarityMultiplier,
        ContentProgressionCurve,
        ContentProgressionDocument,
        ContentPotionEffectTarget,
        ContentPotionItem,
        ContentPotionRarityBonus,
        ContentPotionDocument,
        ContentDiscovery,
        ContentEncounterChoice,
        ContentEncounter,
        ContentEquipmentDescription,
        ContentEquipmentItem,
        ContentEnemy,
        ContentDungeonLevel,
    ):
        session.execute(delete(model))


def _load_progression(session: Session, document: Any) -> int:
    raw = _require_object(document, "progression.json")
    exploration = _required_object(raw, "exploration", "progression.json")
    exploration_rewards = _required_object(exploration, "reward_scaling", "progression.json")
    new_player = _required_object(raw, "new_player", "progression.json")
    combat_leveling = _required_object(raw, "combat_leveling", "progression.json")
    defense = _required_object(raw, "defense", "progression.json")
    enemy_generation = _required_object(raw, "enemy_generation", "progression.json")
    shop = _required_object(raw, "shop", "progression.json")
    document_row = ContentProgressionDocument(
        id=1,
        schema_version=_required_int(raw, "schema_version", "progression.json"),
        exploration_base_cooldown_minutes=_required_int(
            exploration, "base_cooldown_minutes", "progression.json"
        ),
        exploration_min_cooldown_minutes=_required_int(
            exploration, "min_cooldown_minutes", "progression.json"
        ),
        exploration_cooldown_reduction_per_level=_required_int(
            exploration, "cooldown_reduction_per_level", "progression.json"
        ),
        exploration_cooldown_cap_level=_required_int(
            exploration, "cooldown_cap_level", "progression.json"
        ),
        exploration_dungeon_gold_growth=_required_number(
            exploration_rewards, "dungeon_gold_growth", "progression.json"
        ),
        exploration_dungeon_xp_growth=_required_number(
            exploration_rewards, "dungeon_xp_growth", "progression.json"
        ),
        exploration_post_cap_gold_growth=_required_number(
            exploration_rewards, "post_cap_gold_growth", "progression.json"
        ),
        exploration_underpowered_reward_floor=_required_number(
            exploration_rewards, "underpowered_reward_floor", "progression.json"
        ),
        exploration_risk_gold_bonus=_required_number(
            exploration_rewards, "risk_gold_bonus", "progression.json"
        ),
        exploration_failure_xp_multiplier=_required_number(
            exploration_rewards, "failure_xp_multiplier", "progression.json"
        ),
        new_player_base_hp=_required_int(new_player, "base_hp", "progression.json"),
        new_player_attack=_required_int(new_player, "attack", "progression.json"),
        new_player_defense=_required_int(new_player, "defense", "progression.json"),
        new_player_speed=_required_int(new_player, "speed", "progression.json"),
        combat_hp_milestone_interval=_required_int(
            combat_leveling, "hp_milestone_interval", "progression.json"
        ),
        combat_hp_milestone_bonus=_required_int(
            combat_leveling, "hp_milestone_bonus", "progression.json"
        ),
        combat_stat_milestone_interval=_required_int(
            combat_leveling, "stat_milestone_interval", "progression.json"
        ),
        combat_stat_milestone_bonus=_required_int(
            combat_leveling, "stat_milestone_bonus", "progression.json"
        ),
        defense_base_minutes=_required_int(defense, "base_minutes", "progression.json"),
        defense_max_minutes=_required_int(defense, "max_minutes", "progression.json"),
        defense_duration_cap_level=_required_int(defense, "duration_cap_level", "progression.json"),
        defense_restore_full_hp_on_start=_required_bool(
            defense, "restore_full_hp_on_start", "progression.json"
        ),
        defense_post_defeat_hp_percent=_required_number(
            defense, "post_defeat_hp_percent", "progression.json"
        ),
        defense_minimum_damage=_required_int(defense, "minimum_damage", "progression.json"),
        defense_max_battle_rounds=_required_int(defense, "max_battle_rounds", "progression.json"),
        defense_maximum_elapsed_days=_required_int(defense, "maximum_elapsed_days", "progression.json"),
        enemy_generation_level_stat_scale=_required_number(
            enemy_generation, "level_stat_scale", "progression.json"
        ),
        enemy_generation_level_reward_scale=_required_number(
            enemy_generation, "level_reward_scale", "progression.json"
        ),
        enemy_generation_power_xp_floor=_required_number(
            enemy_generation, "power_xp_floor", "progression.json"
        ),
        enemy_generation_power_xp_ceiling=_required_number(
            enemy_generation, "power_xp_ceiling", "progression.json"
        ),
        enemy_generation_trivial_enemy_ratio=_required_number(
            enemy_generation, "trivial_enemy_ratio", "progression.json"
        ),
        enemy_generation_trivial_enemy_xp_multiplier=_required_number(
            enemy_generation, "trivial_enemy_xp_multiplier", "progression.json"
        ),
        enemy_generation_combat_gold_multiplier=_required_number(
            enemy_generation, "combat_gold_multiplier", "progression.json"
        ),
        enemy_generation_trivial_enemy_gold_multiplier=_required_number(
            enemy_generation, "trivial_enemy_gold_multiplier", "progression.json"
        ),
        shop_stock_size=_required_int(shop, "stock_size", "progression.json"),
    )
    session.add(document_row)
    session.flush()

    row_count = 1
    row_count += _load_progression_curve(
        session,
        document_row.id,
        "exploration.leveling",
        _required_object(exploration, "leveling", "progression.json"),
        base_field="base_xp",
        include_minimum=False,
        include_maximum=False,
        include_max_level=True,
    )
    for key, source in (
        ("exploration.reward_scaling.gold_multiplier", exploration_rewards),
        ("exploration.reward_scaling.xp_multiplier", exploration_rewards),
    ):
        row_count += _load_progression_curve(
            session,
            document_row.id,
            key,
            _required_object(source, key.rsplit(".", 1)[-1], "progression.json"),
        )
    for key in ("xp_to_next_level", "hp_per_level", "stat_points_per_level"):
        row_count += _load_progression_curve(
            session,
            document_row.id,
            f"combat_leveling.{key}",
            _required_object(combat_leveling, key, "progression.json"),
        )
    row_count += _load_progression_curve(
        session,
        document_row.id,
        "defense.minutes_per_level",
        _required_object(defense, "minutes_per_level", "progression.json"),
    )
    for key in ("cost_multiplier", "stat_multiplier"):
        row_count += _load_progression_curve(
            session,
            document_row.id,
            f"shop.{key}",
            _required_object(shop, key, "progression.json"),
        )

    for reward_type, field in (
        ("gold", "rarity_gold_multipliers"),
        ("xp", "rarity_xp_multipliers"),
    ):
        for rarity, multiplier in _required_object(exploration_rewards, field, "progression.json").items():
            session.add(
                ContentProgressionRarityMultiplier(
                    document_id=document_row.id,
                    reward_type=reward_type,
                    rarity=str(rarity),
                    multiplier=_number_value(multiplier, f"progression.json.{field}.{rarity}"),
                )
            )
            row_count += 1

    for rarity, weight in _required_object(shop, "rarity_weights", "progression.json").items():
        session.add(
            ContentProgressionShopRarityWeight(
                document_id=document_row.id,
                rarity=str(rarity),
                weight=_int_value(weight, f"progression.json.shop.rarity_weights.{rarity}"),
            )
        )
        row_count += 1

    for index, entry in enumerate(_required_list_field(shop, "rarity_bands", "progression.json")):
        band_source = _require_object(entry, "progression.json.shop.rarity_bands entry")
        band = ContentProgressionShopRarityBand(
            document_id=document_row.id,
            sort_order=index,
            min_level=_required_int(band_source, "min_level", "progression.json"),
        )
        session.add(band)
        session.flush()
        row_count += 1
        weights = _required_object(band_source, "weights", "progression.json")
        for rarity, weight in weights.items():
            session.add(
                ContentProgressionShopRarityBandWeight(
                    band_id=band.id,
                    rarity=str(rarity),
                    weight=_int_value(weight, f"progression.json.shop.rarity_bands.{index}.{rarity}"),
                )
            )
            row_count += 1
    return row_count


def _load_progression_curve(
    session: Session,
    document_id: int,
    key: str,
    source: dict[str, Any],
    *,
    base_field: str = "base",
    include_minimum: bool = True,
    include_maximum: bool = True,
    include_max_level: bool = False,
) -> int:
    session.add(
        ContentProgressionCurve(
            document_id=document_id,
            key=key,
            curve=_required_str(source, "curve", "progression.json"),
            base=_required_number(source, base_field, "progression.json"),
            linear_growth=_required_number(source, "linear_growth", "progression.json"),
            quadratic_growth=_required_number(source, "quadratic_growth", "progression.json"),
            exponential_growth=_required_number(source, "exponential_growth", "progression.json"),
            minimum=_required_number(source, "minimum", "progression.json") if include_minimum else None,
            maximum=_required_number(source, "maximum", "progression.json") if include_maximum else None,
            max_level=_required_int(source, "max_level", "progression.json") if include_max_level else None,
        )
    )
    return 1


def _load_dungeon_levels(session: Session, document: Any) -> int:
    rows = _require_list(document, "dungeon_levels.json")
    for index, entry in enumerate(rows):
        item = _require_object(entry, "dungeon_levels.json entry")
        session.add(
            ContentDungeonLevel(
                sort_order=index,
                level=_required_int(item, "level", "dungeon_levels.json"),
                enemy_level_min=_required_int(item, "enemy_level_min", "dungeon_levels.json"),
                enemy_level_max=_required_int(item, "enemy_level_max", "dungeon_levels.json"),
                stat_modifier=_required_number(item, "stat_modifier", "dungeon_levels.json"),
                reward_modifier=_required_number(item, "reward_modifier", "dungeon_levels.json"),
                target_day=_required_int(item, "target_day", "dungeon_levels.json"),
                exploration_gold_modifier=_required_number(
                    item, "exploration_gold_modifier", "dungeon_levels.json"
                ),
                exploration_xp_modifier=_required_number(
                    item, "exploration_xp_modifier", "dungeon_levels.json"
                ),
                expected_player_power=_required_number(item, "expected_player_power", "dungeon_levels.json"),
                required_explore_level=_required_int(item, "required_explore_level", "dungeon_levels.json"),
                required_combat_level=_required_int(item, "required_combat_level", "dungeon_levels.json"),
                required_equipment_power=_required_number(
                    item, "required_equipment_power", "dungeon_levels.json"
                ),
                required_discoveries=_required_int(item, "required_discoveries", "dungeon_levels.json"),
                required_defense_wins=_required_int(item, "required_defense_wins", "dungeon_levels.json"),
                requires_previous_completion=_required_bool(
                    item, "requires_previous_completion", "dungeon_levels.json"
                ),
                thumbnail_asset=_optional_str(item, "thumbnail_asset", "dungeon_levels.json"),
            )
        )
    return len(rows)


def _load_enemies(session: Session, document: Any) -> int:
    rows = _require_list(document, "enemies.json")
    for index, entry in enumerate(rows):
        item = _require_object(entry, "enemies.json entry")
        session.add(
            ContentEnemy(
                sort_order=index,
                key=_required_str(item, "key", "enemies.json"),
                name=_required_str(item, "name", "enemies.json"),
                min_dungeon_level=_required_int(item, "min_dungeon_level", "enemies.json"),
                max_dungeon_level=_required_int(item, "max_dungeon_level", "enemies.json"),
                base_hp_min=_required_int(item, "base_hp_min", "enemies.json"),
                base_hp_max=_required_int(item, "base_hp_max", "enemies.json"),
                base_attack_min=_required_int(item, "base_attack_min", "enemies.json"),
                base_attack_max=_required_int(item, "base_attack_max", "enemies.json"),
                base_defense_min=_required_int(item, "base_defense_min", "enemies.json"),
                base_defense_max=_required_int(item, "base_defense_max", "enemies.json"),
                base_speed_min=_required_int(item, "base_speed_min", "enemies.json"),
                base_speed_max=_required_int(item, "base_speed_max", "enemies.json"),
                stage_modifier_min=_required_number(item, "stage_modifier_min", "enemies.json"),
                stage_modifier_max=_required_number(item, "stage_modifier_max", "enemies.json"),
                gold_min=_required_int(item, "gold_min", "enemies.json"),
                gold_max=_required_int(item, "gold_max", "enemies.json"),
                xp_min=_required_int(item, "xp_min", "enemies.json"),
                xp_max=_required_int(item, "xp_max", "enemies.json"),
                weight=_required_int(item, "weight", "enemies.json"),
                enabled=_required_bool(item, "enabled", "enemies.json"),
                rank=_required_str(item, "rank", "enemies.json"),
                thumbnail_asset=_optional_str(item, "thumbnail_asset", "enemies.json"),
                emoji_asset=_optional_str(item, "emoji_asset", "enemies.json"),
            )
        )
    return len(rows)


def _load_equipment(session: Session, document: Any) -> int:
    rows = _require_list(document, "equipment.json")
    for index, entry in enumerate(rows):
        item = _require_object(entry, "equipment.json entry")
        session.add(
            ContentEquipmentItem(
                sort_order=index,
                key=_required_str(item, "key", "equipment.json"),
                name=_required_str(item, "name", "equipment.json"),
                slot=_required_str(item, "slot", "equipment.json"),
                rarity=_required_str(item, "rarity", "equipment.json"),
                min_level=_required_int(item, "min_level", "equipment.json"),
                max_level=_required_int(item, "max_level", "equipment.json"),
                cost=_required_int(item, "cost", "equipment.json"),
                hp=_required_int(item, "hp", "equipment.json"),
                attack=_required_int(item, "attack", "equipment.json"),
                defense=_required_int(item, "defense", "equipment.json"),
                speed=_required_int(item, "speed", "equipment.json"),
                thumbnail_asset=_optional_str(item, "thumbnail_asset", "equipment.json"),
            )
        )
    return len(rows)


def _load_equipment_descriptions(session: Session, document: Any) -> int:
    descriptions = _require_object(document, "equipment_descriptions.json")
    for index, (key, description) in enumerate(descriptions.items()):
        if not isinstance(description, str):
            raise ContentDatabaseError("equipment_descriptions.json values must be strings")
        session.add(
            ContentEquipmentDescription(
                sort_order=index,
                equipment_key=str(key),
                description=description,
            )
        )
    return len(descriptions)


def _load_encounters(session: Session, document: Any) -> int:
    rows = _require_list(document, "encounters.json")
    choice_count = 0
    for index, entry in enumerate(rows):
        item = _require_object(entry, "encounters.json entry")
        encounter = ContentEncounter(
            sort_order=index,
            key=_required_str(item, "key", "encounters.json"),
            title=_required_str(item, "title", "encounters.json"),
            description=_required_str(item, "description", "encounters.json"),
            category=_required_str(item, "category", "encounters.json"),
            weight=_required_int(item, "weight", "encounters.json"),
            enabled=_required_bool(item, "enabled", "encounters.json"),
            min_level=_required_int(item, "min_level", "encounters.json"),
            rarity=_required_str(item, "rarity", "encounters.json"),
        )
        session.add(encounter)
        session.flush()
        choices = _required_list_field(item, "choices", "encounters.json")
        for choice_index, choice_entry in enumerate(choices):
            choice = _require_object(choice_entry, f"encounters.json {encounter.key}.choices")
            gold_min = _optional_int(choice, "gold_min", "encounters.json") or 0
            xp_min = _optional_int(choice, "xp_min", "encounters.json") or 0
            session.add(
                ContentEncounterChoice(
                    encounter_id=encounter.id,
                    sort_order=choice_index,
                    key=_required_str(choice, "key", "encounters.json"),
                    label=_required_str(choice, "label", "encounters.json"),
                    result_text=_required_str(choice, "result_text", "encounters.json"),
                    gold_min=gold_min,
                    gold_max=_optional_int(choice, "gold_max", "encounters.json") or gold_min,
                    xp_min=xp_min,
                    xp_max=_optional_int(choice, "xp_max", "encounters.json") or xp_min,
                    hero_effect=_optional_int(choice, "hero_effect", "encounters.json") or 0,
                    villain_effect=_optional_int(choice, "villain_effect", "encounters.json") or 0,
                    stability_effect=_optional_int(choice, "stability_effect", "encounters.json") or 0,
                    success=_optional_bool(choice, "success", "encounters.json", default=True),
                    discovery_key=_optional_str(choice, "discovery_key", "encounters.json"),
                    weekly_progress=_optional_int(choice, "weekly_progress", "encounters.json") or 1,
                )
            )
            choice_count += 1
    return len(rows) + choice_count


def _load_discoveries(session: Session, document: Any) -> int:
    rows = _require_list(document, "discoveries.json")
    for index, entry in enumerate(rows):
        item = _require_object(entry, "discoveries.json entry")
        session.add(
            ContentDiscovery(
                sort_order=index,
                key=_required_str(item, "key", "discoveries.json"),
                name=_required_str(item, "name", "discoveries.json"),
                description=_required_str(item, "description", "discoveries.json"),
                category=_required_str(item, "category", "discoveries.json"),
                rarity=_required_str(item, "rarity", "discoveries.json"),
                image_url=_optional_str(item, "image_url", "discoveries.json"),
                enabled=_required_bool(item, "enabled", "discoveries.json"),
            )
        )
    return len(rows)


def _load_potions(session: Session, document: Any) -> int:
    raw = _require_object(document, "potion_items.json")
    items = _required_list_field(raw, "items", "potion_items.json")
    drop_rules = _required_object(raw, "drop_rules", "potion_items.json")
    activation_rules = _required_object(raw, "activation_rules", "potion_items.json")
    document_row = ContentPotionDocument(
        id=1,
        schema_version=_required_int(raw, "schema_version", "potion_items.json"),
        content_type=_required_str(raw, "content_type", "potion_items.json"),
        balance_intent=_required_str(raw, "balance_intent", "potion_items.json"),
        drop_eligibility_stat=_required_str(drop_rules, "eligibility_stat", "potion_items.json"),
        base_drop_chance=_required_number(drop_rules, "base_drop_chance", "potion_items.json"),
        successful_choice_bonus=_required_number(
            drop_rules, "successful_choice_bonus", "potion_items.json"
        ),
        failed_choice_multiplier=_required_number(
            drop_rules, "failed_choice_multiplier", "potion_items.json"
        ),
        dungeon_level_bonus_per_level_after_one=_required_number(
            drop_rules, "dungeon_level_bonus_per_level_after_one", "potion_items.json"
        ),
        maximum_drop_chance=_required_number(drop_rules, "maximum_drop_chance", "potion_items.json"),
        max_drops_per_exploration=_required_int(
            drop_rules, "max_drops_per_exploration", "potion_items.json"
        ),
        drop_selection_method=_required_str(drop_rules, "selection_method", "potion_items.json"),
        drop_item_weight_field=_required_str(drop_rules, "item_weight_field", "potion_items.json"),
        drop_award_timing=_required_str(drop_rules, "award_timing", "potion_items.json"),
        activation_clock=_required_str(activation_rules, "clock", "potion_items.json"),
        duration_runs_while_offline=_required_bool(
            activation_rules, "duration_runs_while_offline", "potion_items.json"
        ),
        max_simultaneous_effect_groups=_required_int(
            activation_rules, "max_simultaneous_effect_groups", "potion_items.json"
        ),
        same_effect_group_policy=_required_str(
            activation_rules, "same_effect_group_policy", "potion_items.json"
        ),
        replacement_requires_confirmation=_required_bool(
            activation_rules, "replacement_requires_confirmation", "potion_items.json"
        ),
        effects_are_not_retroactive=_required_bool(
            activation_rules, "effects_are_not_retroactive", "potion_items.json"
        ),
        active_at_boundary_rule=_required_str(
            activation_rules, "active_at_boundary_rule", "potion_items.json"
        ),
        healing_occurs_after_victory_only=_required_bool(
            activation_rules, "healing_occurs_after_victory_only", "potion_items.json"
        ),
        xp_potions_affect_defense_combat_xp_only=_required_bool(
            activation_rules, "xp_potions_affect_defense_combat_xp_only", "potion_items.json"
        ),
        luck_affects_enemy_gold_and_combat_xp=_required_bool(
            activation_rules, "luck_affects_enemy_gold_and_combat_xp", "potion_items.json"
        ),
    )
    session.add(document_row)
    session.flush()
    rarity_bonus = _required_object(drop_rules, "encounter_rarity_bonus", "potion_items.json")
    rarity_count = 0
    for rarity, bonus in rarity_bonus.items():
        if not isinstance(bonus, int | float) or isinstance(bonus, bool):
            raise ContentDatabaseError("potion_items.json encounter_rarity_bonus values must be numbers")
        session.add(
            ContentPotionRarityBonus(
                document_id=document_row.id,
                rarity=str(rarity),
                bonus=float(bonus),
            )
        )
        rarity_count += 1
    target_count = 0
    for index, entry in enumerate(items):
        item = _require_object(entry, "potion_items.json item")
        effect = _required_object(item, "effect", "potion_items.json")
        potion = ContentPotionItem(
            sort_order=index,
            key=_required_str(item, "key", "potion_items.json"),
            name=_required_str(item, "name", "potion_items.json"),
            category=_required_str(item, "category", "potion_items.json"),
            potion_type=_required_str(item, "potion_type", "potion_items.json"),
            effect_group=_required_str(item, "effect_group", "potion_items.json"),
            tier=_required_int(item, "tier", "potion_items.json"),
            rarity=_required_str(item, "rarity", "potion_items.json"),
            description=_required_str(item, "description", "potion_items.json"),
            icon_key=_required_str(item, "icon_key", "potion_items.json"),
            duration_seconds=_required_int(item, "duration_seconds", "potion_items.json"),
            min_explore_level=_required_int(item, "min_explore_level", "potion_items.json"),
            max_explore_level=_required_int(item, "max_explore_level", "potion_items.json"),
            exploration_drop_weight=_required_int(
                item, "exploration_drop_weight", "potion_items.json"
            ),
            inventory_stack_limit=_required_int(item, "inventory_stack_limit", "potion_items.json"),
            consumable=_required_bool(item, "consumable", "potion_items.json"),
            enabled=_required_bool(item, "enabled", "potion_items.json"),
            sort_order_value=_required_int(item, "sort_order", "potion_items.json"),
            effect_kind=_required_str(effect, "kind", "potion_items.json"),
            effect_operation=_required_str(effect, "operation", "potion_items.json"),
            effect_bonus=_optional_number(effect, "bonus", "potion_items.json"),
            effect_final_multiplier=_optional_number(effect, "final_multiplier", "potion_items.json"),
            effect_chance=_optional_number(effect, "chance", "potion_items.json"),
            effect_max_hp_percent=_optional_number(effect, "max_hp_percent", "potion_items.json"),
            effect_flat_cap=_optional_int(effect, "flat_cap", "potion_items.json"),
            effect_minimum_heal=_optional_int(effect, "minimum_heal", "potion_items.json"),
            effect_heals_on_activation=_optional_bool_or_none(
                effect, "heals_on_activation", "potion_items.json"
            ),
            effect_trigger=_optional_str(effect, "trigger", "potion_items.json"),
            effect_proc_scope=_optional_str(effect, "proc_scope", "potion_items.json"),
            thumbnail_asset=_optional_str(item, "thumbnail_asset", "potion_items.json"),
        )
        session.add(potion)
        session.flush()
        applies_to = effect.get("applies_to", [])
        if applies_to is None:
            applies_to = []
        if not isinstance(applies_to, list):
            raise ContentDatabaseError("potion_items.json effect.applies_to must be a list")
        for target_index, target in enumerate(applies_to):
            if not isinstance(target, str) or not target:
                raise ContentDatabaseError("potion_items.json effect.applies_to values must be strings")
            session.add(
                ContentPotionEffectTarget(
                    potion_item_id=potion.id,
                    sort_order=target_index,
                    target=target,
                )
            )
            target_count += 1
    return len(items) + rarity_count + target_count + 1


def _load_locations(session: Session, document: Any) -> int:
    rows = _require_list(document, "locations.json")
    for index, entry in enumerate(rows):
        item = _require_object(entry, "locations.json entry")
        session.add(
            ContentLocation(
                sort_order=index,
                key=_required_str(item, "key", "locations.json"),
                name=_required_str(item, "name", "locations.json"),
                banner_asset=_required_str(item, "banner_asset", "locations.json"),
            )
        )
    return len(rows)


def _load_image_assets(session: Session, document: Any) -> int:
    raw = _require_object(document, "image_assets.json")
    assets = _required_object(raw, "assets", "image_assets.json")
    session.add(
        ContentImageAssetDocument(
            id=1,
            version=_required_int(raw, "version", "image_assets.json"),
        )
    )
    for index, (asset_key, entry) in enumerate(assets.items()):
        item = _require_object(entry, f"image_assets.json {asset_key}")
        session.add(
            ContentImageAsset(
                sort_order=index,
                asset_key=str(asset_key),
                type=_required_str(item, "type", "image_assets.json"),
                path=_required_str(item, "path", "image_assets.json"),
                alt_text=_optional_str(item, "alt_text", "image_assets.json") or _default_asset_alt_text(str(asset_key)),
                required=_optional_bool(item, "required", "image_assets.json", default=False),
                source_path=_optional_str(item, "source_path", "image_assets.json"),
            )
        )
    return len(assets) + 1


def _load_image_asset_registry(session: Session, document: Any) -> int:
    raw = _require_object(document, "image_asset_registry.json")
    assets = _required_object(raw, "assets", "image_asset_registry.json")
    session.add(
        ContentImageAssetRegistryDocument(
            id=1,
            version=_required_int(raw, "version", "image_asset_registry.json"),
        )
    )
    for index, (asset_key, entry) in enumerate(assets.items()):
        item = _require_object(entry, f"image_asset_registry.json {asset_key}")
        session.add(
            ContentImageAssetRegistryEntry(
                sort_order=index,
                asset_key=str(asset_key),
                type=_optional_str(item, "type", "image_asset_registry.json"),
                filename=_optional_str(item, "filename", "image_asset_registry.json"),
                sha256=_optional_str(item, "sha256", "image_asset_registry.json"),
                width=_optional_int(item, "width", "image_asset_registry.json"),
                height=_optional_int(item, "height", "image_asset_registry.json"),
                size_bytes=_optional_int(item, "size_bytes", "image_asset_registry.json"),
                channel_id=_optional_stringified(item, "channel_id"),
                message_id=_optional_stringified(item, "message_id"),
                attachment_id=_optional_stringified(item, "attachment_id"),
                cdn_url=_optional_str(item, "cdn_url", "image_asset_registry.json"),
                uploaded_at=_optional_str(item, "uploaded_at", "image_asset_registry.json"),
            )
        )
    return len(assets) + 1


def _sync_runtime_discoveries(session: Session) -> None:
    rows = session.scalars(
        select(ContentDiscovery).order_by(ContentDiscovery.sort_order, ContentDiscovery.key)
    ).all()
    active_keys: set[str] = set()
    for row in rows:
        active_keys.add(row.key)
        discovery = session.scalar(select(Discovery).where(Discovery.key == row.key))
        if discovery is None:
            discovery = Discovery(key=row.key)
            session.add(discovery)
        discovery.name = row.name
        discovery.description = row.description
        discovery.category = row.category
        discovery.rarity = row.rarity
        discovery.image_url = row.image_url
        discovery.enabled = row.enabled
    if active_keys:
        for discovery in session.scalars(select(Discovery).where(Discovery.key.not_in(active_keys))).all():
            discovery.enabled = False


def _dump_progression(session: Session) -> dict[str, Any]:
    row = session.scalar(
        select(ContentProgressionDocument)
        .options(
            selectinload(ContentProgressionDocument.curves),
            selectinload(ContentProgressionDocument.rarity_multipliers),
            selectinload(ContentProgressionDocument.shop_rarity_weights),
            selectinload(ContentProgressionDocument.shop_rarity_bands).selectinload(
                ContentProgressionShopRarityBand.weights
            ),
        )
        .where(ContentProgressionDocument.id == 1)
    )
    if row is None:
        raise ContentDatabaseError("Cannot dump progression.json; singleton row id=1 is not loaded")
    curves = {curve.key: curve for curve in row.curves}
    return {
        "schema_version": row.schema_version,
        "exploration": {
            "base_cooldown_minutes": row.exploration_base_cooldown_minutes,
            "min_cooldown_minutes": row.exploration_min_cooldown_minutes,
            "cooldown_reduction_per_level": row.exploration_cooldown_reduction_per_level,
            "cooldown_cap_level": row.exploration_cooldown_cap_level,
            "leveling": _progression_curve_dict(
                curves,
                "exploration.leveling",
                base_field="base_xp",
                include_minimum=False,
                include_maximum=False,
                include_max_level=True,
            ),
            "reward_scaling": {
                "gold_multiplier": _progression_curve_dict(
                    curves, "exploration.reward_scaling.gold_multiplier"
                ),
                "xp_multiplier": _progression_curve_dict(
                    curves, "exploration.reward_scaling.xp_multiplier"
                ),
                "dungeon_gold_growth": row.exploration_dungeon_gold_growth,
                "dungeon_xp_growth": row.exploration_dungeon_xp_growth,
                "post_cap_gold_growth": row.exploration_post_cap_gold_growth,
                "underpowered_reward_floor": row.exploration_underpowered_reward_floor,
                "risk_gold_bonus": row.exploration_risk_gold_bonus,
                "failure_xp_multiplier": row.exploration_failure_xp_multiplier,
                "rarity_gold_multipliers": _progression_rarity_multipliers(row, "gold"),
                "rarity_xp_multipliers": _progression_rarity_multipliers(row, "xp"),
            },
        },
        "new_player": {
            "base_hp": row.new_player_base_hp,
            "attack": row.new_player_attack,
            "defense": row.new_player_defense,
            "speed": row.new_player_speed,
        },
        "combat_leveling": {
            "xp_to_next_level": _progression_curve_dict(curves, "combat_leveling.xp_to_next_level"),
            "hp_per_level": _progression_curve_dict(curves, "combat_leveling.hp_per_level"),
            "stat_points_per_level": _progression_curve_dict(
                curves, "combat_leveling.stat_points_per_level"
            ),
            "hp_milestone_interval": row.combat_hp_milestone_interval,
            "hp_milestone_bonus": row.combat_hp_milestone_bonus,
            "stat_milestone_interval": row.combat_stat_milestone_interval,
            "stat_milestone_bonus": row.combat_stat_milestone_bonus,
        },
        "defense": {
            "base_minutes": row.defense_base_minutes,
            "max_minutes": row.defense_max_minutes,
            "minutes_per_level": _progression_curve_dict(curves, "defense.minutes_per_level"),
            "duration_cap_level": row.defense_duration_cap_level,
            "restore_full_hp_on_start": row.defense_restore_full_hp_on_start,
            "post_defeat_hp_percent": row.defense_post_defeat_hp_percent,
            "minimum_damage": row.defense_minimum_damage,
            "max_battle_rounds": row.defense_max_battle_rounds,
            "maximum_elapsed_days": row.defense_maximum_elapsed_days,
        },
        "enemy_generation": {
            "level_stat_scale": row.enemy_generation_level_stat_scale,
            "level_reward_scale": row.enemy_generation_level_reward_scale,
            "power_xp_floor": row.enemy_generation_power_xp_floor,
            "power_xp_ceiling": row.enemy_generation_power_xp_ceiling,
            "trivial_enemy_ratio": row.enemy_generation_trivial_enemy_ratio,
            "trivial_enemy_xp_multiplier": row.enemy_generation_trivial_enemy_xp_multiplier,
            "combat_gold_multiplier": row.enemy_generation_combat_gold_multiplier,
            "trivial_enemy_gold_multiplier": row.enemy_generation_trivial_enemy_gold_multiplier,
        },
        "shop": {
            "stock_size": row.shop_stock_size,
            "cost_multiplier": _progression_curve_dict(curves, "shop.cost_multiplier"),
            "stat_multiplier": _progression_curve_dict(curves, "shop.stat_multiplier"),
            "rarity_weights": {entry.rarity: entry.weight for entry in row.shop_rarity_weights},
            "rarity_bands": [
                {
                    "min_level": band.min_level,
                    "weights": {entry.rarity: entry.weight for entry in band.weights},
                }
                for band in row.shop_rarity_bands
            ],
        },
    }


def _progression_curve_dict(
    curves: dict[str, ContentProgressionCurve],
    key: str,
    *,
    base_field: str = "base",
    include_minimum: bool = True,
    include_maximum: bool = True,
    include_max_level: bool = False,
) -> dict[str, Any]:
    try:
        curve = curves[key]
    except KeyError as error:
        raise ContentDatabaseError(f"Cannot dump progression.json; missing curve {key}") from error
    output: dict[str, Any] = {
        "curve": curve.curve,
        base_field: curve.base,
        "linear_growth": curve.linear_growth,
        "quadratic_growth": curve.quadratic_growth,
        "exponential_growth": curve.exponential_growth,
    }
    if include_minimum:
        output["minimum"] = curve.minimum
    if include_maximum:
        output["maximum"] = curve.maximum
    if include_max_level:
        output["max_level"] = curve.max_level
    return output


def _progression_rarity_multipliers(
    row: ContentProgressionDocument,
    reward_type: str,
) -> dict[str, float]:
    return {
        entry.rarity: entry.multiplier
        for entry in row.rarity_multipliers
        if entry.reward_type == reward_type
    }


def _dump_dungeon_levels(session: Session) -> list[dict[str, Any]]:
    return _dump_rows(
        session,
        ContentDungeonLevel,
        (
            ("level", "level"),
            ("enemy_level_min", "enemy_level_min"),
            ("enemy_level_max", "enemy_level_max"),
            ("stat_modifier", "stat_modifier"),
            ("reward_modifier", "reward_modifier"),
            ("target_day", "target_day"),
            ("exploration_gold_modifier", "exploration_gold_modifier"),
            ("exploration_xp_modifier", "exploration_xp_modifier"),
            ("expected_player_power", "expected_player_power"),
            ("required_explore_level", "required_explore_level"),
            ("required_combat_level", "required_combat_level"),
            ("required_equipment_power", "required_equipment_power"),
            ("required_discoveries", "required_discoveries"),
            ("required_defense_wins", "required_defense_wins"),
            ("requires_previous_completion", "requires_previous_completion"),
            ("thumbnail_asset", "thumbnail_asset"),
        ),
        "dungeon_levels.json",
        optional_fields={"thumbnail_asset"},
    )


def _dump_enemies(session: Session) -> list[dict[str, Any]]:
    return _dump_rows(
        session,
        ContentEnemy,
        (
            ("key", "key"),
            ("name", "name"),
            ("min_dungeon_level", "min_dungeon_level"),
            ("max_dungeon_level", "max_dungeon_level"),
            ("base_hp_min", "base_hp_min"),
            ("base_hp_max", "base_hp_max"),
            ("base_attack_min", "base_attack_min"),
            ("base_attack_max", "base_attack_max"),
            ("base_defense_min", "base_defense_min"),
            ("base_defense_max", "base_defense_max"),
            ("base_speed_min", "base_speed_min"),
            ("base_speed_max", "base_speed_max"),
            ("stage_modifier_min", "stage_modifier_min"),
            ("stage_modifier_max", "stage_modifier_max"),
            ("gold_min", "gold_min"),
            ("gold_max", "gold_max"),
            ("xp_min", "xp_min"),
            ("xp_max", "xp_max"),
            ("weight", "weight"),
            ("enabled", "enabled"),
            ("rank", "rank"),
            ("thumbnail_asset", "thumbnail_asset"),
            ("emoji_asset", "emoji_asset"),
        ),
        "enemies.json",
        optional_fields={"thumbnail_asset", "emoji_asset"},
    )


def _dump_equipment(session: Session) -> list[dict[str, Any]]:
    return _dump_rows(
        session,
        ContentEquipmentItem,
        (
            ("key", "key"),
            ("name", "name"),
            ("slot", "slot"),
            ("rarity", "rarity"),
            ("min_level", "min_level"),
            ("max_level", "max_level"),
            ("cost", "cost"),
            ("hp", "hp"),
            ("attack", "attack"),
            ("defense", "defense"),
            ("speed", "speed"),
            ("thumbnail_asset", "thumbnail_asset"),
        ),
        "equipment.json",
        optional_fields={"thumbnail_asset"},
    )


def _dump_equipment_descriptions(session: Session) -> dict[str, str]:
    rows = session.scalars(
        select(ContentEquipmentDescription).order_by(
            ContentEquipmentDescription.sort_order,
            ContentEquipmentDescription.equipment_key,
        )
    ).all()
    if not rows:
        raise ContentDatabaseError("Cannot dump equipment_descriptions.json; no rows are loaded")
    return {row.equipment_key: row.description for row in rows}


def _dump_encounters(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(ContentEncounter)
        .options(selectinload(ContentEncounter.choices))
        .order_by(ContentEncounter.sort_order, ContentEncounter.id)
    ).all()
    if not rows:
        raise ContentDatabaseError("Cannot dump encounters.json; no rows are loaded")
    output: list[dict[str, Any]] = []
    for row in rows:
        item = _payload_with(
            row,
            (
                ("key", "key"),
                ("title", "title"),
                ("description", "description"),
                ("category", "category"),
                ("weight", "weight"),
                ("enabled", "enabled"),
                ("min_level", "min_level"),
                ("rarity", "rarity"),
            ),
        )
        choices = []
        for choice in row.choices:
            choices.append(
                _payload_with(
                    choice,
                    (
                        ("key", "key"),
                        ("label", "label"),
                        ("result_text", "result_text"),
                        ("gold_min", "gold_min"),
                        ("gold_max", "gold_max"),
                        ("xp_min", "xp_min"),
                        ("xp_max", "xp_max"),
                        ("hero_effect", "hero_effect"),
                        ("villain_effect", "villain_effect"),
                        ("stability_effect", "stability_effect"),
                        ("success", "success"),
                        ("discovery_key", "discovery_key"),
                        ("weekly_progress", "weekly_progress"),
                    ),
                    optional_fields={
                        "hero_effect",
                        "villain_effect",
                        "stability_effect",
                        "success",
                        "discovery_key",
                        "weekly_progress",
                    },
                    default_optional_values={
                        "hero_effect": 0,
                        "villain_effect": 0,
                        "stability_effect": 0,
                        "success": True,
                        "weekly_progress": 1,
                    },
                )
            )
        item["choices"] = choices
        output.append(item)
    return output


def _dump_discoveries(session: Session) -> list[dict[str, Any]]:
    return _dump_rows(
        session,
        ContentDiscovery,
        (
            ("key", "key"),
            ("name", "name"),
            ("description", "description"),
            ("category", "category"),
            ("rarity", "rarity"),
            ("image_url", "image_url"),
            ("enabled", "enabled"),
        ),
        "discoveries.json",
        optional_fields={"image_url"},
    )


def _dump_potions(session: Session) -> dict[str, Any]:
    document = _require_singleton(session, ContentPotionDocument, "potion_items.json")
    output = {
        "schema_version": document.schema_version,
        "content_type": document.content_type,
        "balance_intent": document.balance_intent,
        "drop_rules": {
            "eligibility_stat": document.drop_eligibility_stat,
            "base_drop_chance": document.base_drop_chance,
            "successful_choice_bonus": document.successful_choice_bonus,
            "failed_choice_multiplier": document.failed_choice_multiplier,
            "dungeon_level_bonus_per_level_after_one": (
                document.dungeon_level_bonus_per_level_after_one
            ),
            "encounter_rarity_bonus": {
                row.rarity: row.bonus for row in document.encounter_rarity_bonuses
            },
            "maximum_drop_chance": document.maximum_drop_chance,
            "max_drops_per_exploration": document.max_drops_per_exploration,
            "selection_method": document.drop_selection_method,
            "item_weight_field": document.drop_item_weight_field,
            "award_timing": document.drop_award_timing,
        },
        "activation_rules": {
            "clock": document.activation_clock,
            "duration_runs_while_offline": document.duration_runs_while_offline,
            "max_simultaneous_effect_groups": document.max_simultaneous_effect_groups,
            "same_effect_group_policy": document.same_effect_group_policy,
            "replacement_requires_confirmation": document.replacement_requires_confirmation,
            "effects_are_not_retroactive": document.effects_are_not_retroactive,
            "active_at_boundary_rule": document.active_at_boundary_rule,
            "healing_occurs_after_victory_only": document.healing_occurs_after_victory_only,
            "xp_potions_affect_defense_combat_xp_only": (
                document.xp_potions_affect_defense_combat_xp_only
            ),
            "luck_affects_enemy_gold_and_combat_xp": (
                document.luck_affects_enemy_gold_and_combat_xp
            ),
        },
    }
    rows = session.scalars(
        select(ContentPotionItem)
        .options(selectinload(ContentPotionItem.effect_targets))
        .order_by(ContentPotionItem.sort_order, ContentPotionItem.id)
    ).all()
    if not rows:
        raise ContentDatabaseError("Cannot dump potion_items.json; no rows are loaded")
    output["items"] = [_dump_potion_item(row) for row in rows]
    return output


def _dump_potion_item(row: ContentPotionItem) -> dict[str, Any]:
    item = _payload_with(
        row,
        (
            ("key", "key"),
            ("name", "name"),
            ("category", "category"),
            ("potion_type", "potion_type"),
            ("effect_group", "effect_group"),
            ("tier", "tier"),
            ("rarity", "rarity"),
            ("description", "description"),
            ("icon_key", "icon_key"),
            ("duration_seconds", "duration_seconds"),
            ("min_explore_level", "min_explore_level"),
            ("max_explore_level", "max_explore_level"),
            ("exploration_drop_weight", "exploration_drop_weight"),
            ("inventory_stack_limit", "inventory_stack_limit"),
            ("consumable", "consumable"),
            ("enabled", "enabled"),
            ("thumbnail_asset", "thumbnail_asset"),
            ("sort_order", "sort_order_value"),
        ),
        optional_fields={"thumbnail_asset"},
    )
    effect: dict[str, Any] = {
        "kind": row.effect_kind,
        "operation": row.effect_operation,
    }
    _include_optional(effect, "bonus", row.effect_bonus)
    _include_optional(effect, "final_multiplier", row.effect_final_multiplier)
    _include_optional(effect, "chance", row.effect_chance)
    _include_optional(effect, "max_hp_percent", row.effect_max_hp_percent)
    _include_optional(effect, "flat_cap", row.effect_flat_cap)
    _include_optional(effect, "minimum_heal", row.effect_minimum_heal)
    _include_optional(effect, "heals_on_activation", row.effect_heals_on_activation)
    _include_optional(effect, "trigger", row.effect_trigger)
    _include_optional(effect, "proc_scope", row.effect_proc_scope)
    targets = [target.target for target in row.effect_targets]
    if targets:
        effect["applies_to"] = targets
    item["effect"] = effect
    return item


def _dump_locations(session: Session) -> list[dict[str, Any]]:
    return _dump_rows(
        session,
        ContentLocation,
        (("key", "key"), ("name", "name"), ("banner_asset", "banner_asset")),
        "locations.json",
    )


def _dump_image_assets(session: Session) -> dict[str, Any]:
    document = _require_singleton(session, ContentImageAssetDocument, "image_assets.json")
    output = _payload_with(document, (("version", "version"),))
    rows = session.scalars(
        select(ContentImageAsset).order_by(ContentImageAsset.sort_order, ContentImageAsset.asset_key)
    ).all()
    output["assets"] = {
        row.asset_key: _payload_with(
            row,
            (
                ("type", "type"),
                ("path", "path"),
                ("alt_text", "alt_text"),
                ("required", "required"),
                ("source_path", "source_path"),
            ),
            optional_fields={"alt_text", "required", "source_path"},
            default_optional_values={
                "alt_text": _default_asset_alt_text(row.asset_key),
                "required": False,
            },
        )
        for row in rows
    }
    return output


def _dump_image_asset_registry(session: Session) -> dict[str, Any]:
    document = _require_singleton(
        session, ContentImageAssetRegistryDocument, "image_asset_registry.json"
    )
    output = _payload_with(document, (("version", "version"),))
    rows = session.scalars(
        select(ContentImageAssetRegistryEntry).order_by(
            ContentImageAssetRegistryEntry.sort_order,
            ContentImageAssetRegistryEntry.asset_key,
        )
    ).all()
    fields = (
        ("type", "type"),
        ("filename", "filename"),
        ("sha256", "sha256"),
        ("width", "width"),
        ("height", "height"),
        ("size_bytes", "size_bytes"),
        ("channel_id", "channel_id"),
        ("message_id", "message_id"),
        ("attachment_id", "attachment_id"),
        ("cdn_url", "cdn_url"),
        ("uploaded_at", "uploaded_at"),
    )
    output["assets"] = {
        row.asset_key: _payload_with(row, fields, optional_fields={name for name, _ in fields})
        for row in rows
    }
    return output


def _dump_rows(
    session: Session,
    model: type[Any],
    fields: tuple[tuple[str, str], ...],
    filename: str,
    *,
    optional_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows = session.scalars(select(model).order_by(model.sort_order, model.id)).all()
    if not rows:
        raise ContentDatabaseError(f"Cannot dump {filename}; no rows are loaded")
    return [_payload_with(row, fields, optional_fields=optional_fields or set()) for row in rows]


def _payload_with(
    row: Any,
    fields: tuple[tuple[str, str], ...],
    *,
    optional_fields: set[str] | None = None,
    default_optional_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    optional = optional_fields or set()
    optional_defaults = default_optional_values or {}
    output: dict[str, Any] = {}
    for json_name, attribute_name in fields:
        value = getattr(row, attribute_name)
        if json_name in optional:
            if value is None:
                continue
            if json_name in optional_defaults and value == optional_defaults[json_name]:
                continue
        output[json_name] = value
    return output


def _include_optional(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def _default_asset_alt_text(asset_key: str) -> str:
    return asset_key.replace(".", " ").replace("_", " ").title()


def _require_singleton(session: Session, model: type[Any], filename: str) -> Any:
    row = session.get(model, 1)
    if row is None:
        raise ContentDatabaseError(f"Cannot dump {filename}; singleton row id=1 is not loaded")
    return row


def _dump_row_counts(documents: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for filename, document in documents.items():
        if isinstance(document, list):
            counts[filename] = len(document)
        elif filename == "equipment_descriptions.json":
            counts[filename] = len(document)
        elif filename == "potion_items.json":
            counts[filename] = 1 + len(document.get("items", []))
        elif filename in {"image_assets.json", "image_asset_registry.json"}:
            counts[filename] = 1 + len(document.get("assets", {}))
        elif isinstance(document, dict):
            counts[filename] = 1
        else:
            counts[filename] = 0
    return counts


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise ContentDatabaseError(f"Missing content file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContentDatabaseError(f"{path.name} is invalid JSON: {error}") from error


def _write_json(path: Path, value: Any, *, indent: int) -> None:
    path.write_text(json.dumps(value, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContentDatabaseError(f"{context} must be a JSON object")
    return value


def _require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContentDatabaseError(f"{context} must be a JSON array")
    return value


def _required_object(source: dict[str, Any], key: str, context: str) -> dict[str, Any]:
    return _require_object(_required_value(source, key, context), f"{context}.{key}")


def _required_list_field(source: dict[str, Any], key: str, context: str) -> list[Any]:
    return _require_list(_required_value(source, key, context), f"{context}.{key}")


def _required_str(source: dict[str, Any], key: str, context: str) -> str:
    value = _required_value(source, key, context)
    if not isinstance(value, str):
        raise ContentDatabaseError(f"{context}.{key} must be a string")
    return value


def _optional_str(source: dict[str, Any], key: str, context: str) -> str | None:
    if key not in source or source[key] is None:
        return None
    return _required_str(source, key, context)


def _optional_stringified(source: dict[str, Any], key: str) -> str | None:
    if key not in source or source[key] is None:
        return None
    return str(source[key])


def _required_int(source: dict[str, Any], key: str, context: str) -> int:
    value = _required_value(source, key, context)
    return _int_value(value, f"{context}.{key}")


def _int_value(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContentDatabaseError(f"{context} must be an integer")
    return value


def _optional_int(source: dict[str, Any], key: str, context: str) -> int | None:
    if key not in source or source[key] is None:
        return None
    return _required_int(source, key, context)


def _optional_number(source: dict[str, Any], key: str, context: str) -> float | None:
    if key not in source or source[key] is None:
        return None
    return _required_number(source, key, context)


def _required_number(source: dict[str, Any], key: str, context: str) -> float:
    value = _required_value(source, key, context)
    return _number_value(value, f"{context}.{key}")


def _number_value(value: Any, context: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ContentDatabaseError(f"{context} must be a number")
    return float(value)


def _required_bool(source: dict[str, Any], key: str, context: str) -> bool:
    value = _required_value(source, key, context)
    if not isinstance(value, bool):
        raise ContentDatabaseError(f"{context}.{key} must be a boolean")
    return value


def _optional_bool(source: dict[str, Any], key: str, context: str, *, default: bool) -> bool:
    if key not in source or source[key] is None:
        return default
    return _required_bool(source, key, context)


def _optional_bool_or_none(source: dict[str, Any], key: str, context: str) -> bool | None:
    if key not in source or source[key] is None:
        return None
    return _required_bool(source, key, context)


def _required_value(source: dict[str, Any], key: str, context: str) -> Any:
    if key not in source:
        raise ContentDatabaseError(f"{context} is missing required field {key}")
    return source[key]
