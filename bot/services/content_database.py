from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bot.models import (
    ContentDiscovery,
    ContentDungeonLevel,
    ContentEncounter,
    ContentEnemy,
    ContentEquipmentDescription,
    ContentEquipmentItem,
    ContentImageAsset,
    ContentImageAssetDocument,
    ContentImageAssetRegistryDocument,
    ContentImageAssetRegistryEntry,
    ContentLocation,
    ContentPotionDocument,
    ContentPotionItem,
    ContentProgressionDocument,
    ContentSimulationResult,
    ContentValidationReport,
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
    "content_validation.json",
    "simulation_results.json",
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
        "content_validation.json": _load_validation_report(
            session, documents["content_validation.json"]
        ),
        "simulation_results.json": _load_simulation_results(
            session, documents["simulation_results.json"]
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
        "content_validation.json": _dump_validation_report(session),
        "simulation_results.json": _dump_simulation_results(session),
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
        "content_validation.json": _dump_validation_report(session),
        "simulation_results.json": _dump_simulation_results(session),
    }


def sync_runtime_discoveries_from_content_tables(session: Session) -> None:
    _sync_runtime_discoveries(session)


def _clear_content_tables(session: Session) -> None:
    for model in (
        ContentSimulationResult,
        ContentValidationReport,
        ContentImageAssetRegistryEntry,
        ContentImageAssetRegistryDocument,
        ContentImageAsset,
        ContentImageAssetDocument,
        ContentLocation,
        ContentProgressionDocument,
        ContentPotionItem,
        ContentPotionDocument,
        ContentDiscovery,
        ContentEncounter,
        ContentEquipmentDescription,
        ContentEquipmentItem,
        ContentEnemy,
        ContentDungeonLevel,
    ):
        session.execute(delete(model))


def _load_progression(session: Session, document: Any) -> int:
    raw = _require_object(document, "progression.json")
    session.add(
        ContentProgressionDocument(
            id=1,
            schema_version=_required_int(raw, "schema_version", "progression.json"),
            exploration=_required_object(raw, "exploration", "progression.json"),
            new_player=_required_object(raw, "new_player", "progression.json"),
            combat_leveling=_required_object(raw, "combat_leveling", "progression.json"),
            defense=_required_object(raw, "defense", "progression.json"),
            enemy_generation=_required_object(raw, "enemy_generation", "progression.json"),
            shop=_required_object(raw, "shop", "progression.json"),
            payload=dict(raw),
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
                payload=dict(item),
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
                payload=dict(item),
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
                payload=dict(item),
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
    for index, entry in enumerate(rows):
        item = _require_object(entry, "encounters.json entry")
        session.add(
            ContentEncounter(
                sort_order=index,
                key=_required_str(item, "key", "encounters.json"),
                title=_required_str(item, "title", "encounters.json"),
                description=_required_str(item, "description", "encounters.json"),
                category=_required_str(item, "category", "encounters.json"),
                weight=_required_int(item, "weight", "encounters.json"),
                enabled=_required_bool(item, "enabled", "encounters.json"),
                min_level=_required_int(item, "min_level", "encounters.json"),
                rarity=_required_str(item, "rarity", "encounters.json"),
                choices=_required_list_field(item, "choices", "encounters.json"),
                payload=dict(item),
            )
        )
    return len(rows)


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
                payload=dict(item),
            )
        )
    return len(rows)


def _load_potions(session: Session, document: Any) -> int:
    raw = _require_object(document, "potion_items.json")
    items = _required_list_field(raw, "items", "potion_items.json")
    session.add(
        ContentPotionDocument(
            id=1,
            schema_version=_required_int(raw, "schema_version", "potion_items.json"),
            content_type=_required_str(raw, "content_type", "potion_items.json"),
            balance_intent=_required_str(raw, "balance_intent", "potion_items.json"),
            drop_rules=_required_object(raw, "drop_rules", "potion_items.json"),
            activation_rules=_required_object(raw, "activation_rules", "potion_items.json"),
            payload=dict(raw),
        )
    )
    for index, entry in enumerate(items):
        item = _require_object(entry, "potion_items.json item")
        session.add(
            ContentPotionItem(
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
                effect=_required_object(item, "effect", "potion_items.json"),
                thumbnail_asset=_optional_str(item, "thumbnail_asset", "potion_items.json"),
                payload=dict(item),
            )
        )
    return len(items) + 1


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
                payload=dict(item),
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
            payload=dict(raw),
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
                alt_text=_required_str(item, "alt_text", "image_assets.json"),
                required=_required_bool(item, "required", "image_assets.json"),
                source_path=_optional_str(item, "source_path", "image_assets.json"),
                payload=dict(item),
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
            payload=dict(raw),
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
                payload=dict(item),
            )
        )
    return len(assets) + 1


def _load_validation_report(session: Session, document: Any) -> int:
    raw = _require_object(document, "content_validation.json")
    session.add(
        ContentValidationReport(
            id=1,
            passed=_required_bool(raw, "passed", "content_validation.json"),
            errors=_required_list_field(raw, "errors", "content_validation.json"),
            counts=_required_object(raw, "counts", "content_validation.json"),
            potions_by_group=_required_object(raw, "potions_by_group", "content_validation.json"),
            equipment_by_slot=_required_object(raw, "equipment_by_slot", "content_validation.json"),
            equipment_by_rarity=_required_object(raw, "equipment_by_rarity", "content_validation.json"),
            equipment_valid_options=_required_object(raw, "equipment_valid_options", "content_validation.json"),
            shop_rarity_percentages=_required_object(raw, "shop_rarity_percentages", "content_validation.json"),
            content_coverage=_required_object(raw, "content_coverage", "content_validation.json"),
            payload=dict(raw),
        )
    )
    return 1


def _load_simulation_results(session: Session, document: Any) -> int:
    raw = _require_object(document, "simulation_results.json")
    session.add(
        ContentSimulationResult(
            id=1,
            assumptions=_required_object(raw, "assumptions", "simulation_results.json"),
            shop_rarity_percentages=_required_object(
                raw, "shop_rarity_percentages", "simulation_results.json"
            ),
            profiles=_required_object(raw, "profiles", "simulation_results.json"),
            target_evaluation=_required_object(raw, "target_evaluation", "simulation_results.json"),
            payload=dict(raw),
        )
    )
    return 1


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
    row = _require_singleton(session, ContentProgressionDocument, "progression.json")
    return _payload_with(
        row,
        (
            ("schema_version", "schema_version"),
            ("exploration", "exploration"),
            ("new_player", "new_player"),
            ("combat_leveling", "combat_leveling"),
            ("defense", "defense"),
            ("enemy_generation", "enemy_generation"),
            ("shop", "shop"),
        ),
    )


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
        ),
        "dungeon_levels.json",
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
        ),
        "enemies.json",
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
    return _dump_rows(
        session,
        ContentEncounter,
        (
            ("key", "key"),
            ("title", "title"),
            ("description", "description"),
            ("category", "category"),
            ("weight", "weight"),
            ("enabled", "enabled"),
            ("min_level", "min_level"),
            ("rarity", "rarity"),
            ("choices", "choices"),
        ),
        "encounters.json",
    )


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
    output = _payload_with(
        document,
        (
            ("schema_version", "schema_version"),
            ("content_type", "content_type"),
            ("balance_intent", "balance_intent"),
            ("drop_rules", "drop_rules"),
            ("activation_rules", "activation_rules"),
        ),
    )
    output["items"] = _dump_rows(
        session,
        ContentPotionItem,
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
            ("sort_order", "sort_order_value"),
            ("effect", "effect"),
            ("thumbnail_asset", "thumbnail_asset"),
        ),
        "potion_items.json",
        optional_fields={"thumbnail_asset"},
    )
    return output


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
            optional_fields={"source_path"},
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


def _dump_validation_report(session: Session) -> dict[str, Any]:
    row = _require_singleton(session, ContentValidationReport, "content_validation.json")
    return _payload_with(
        row,
        (
            ("passed", "passed"),
            ("errors", "errors"),
            ("counts", "counts"),
            ("potions_by_group", "potions_by_group"),
            ("equipment_by_slot", "equipment_by_slot"),
            ("equipment_by_rarity", "equipment_by_rarity"),
            ("equipment_valid_options", "equipment_valid_options"),
            ("shop_rarity_percentages", "shop_rarity_percentages"),
            ("content_coverage", "content_coverage"),
        ),
    )


def _dump_simulation_results(session: Session) -> dict[str, Any]:
    row = _require_singleton(session, ContentSimulationResult, "simulation_results.json")
    return _payload_with(
        row,
        (
            ("assumptions", "assumptions"),
            ("shop_rarity_percentages", "shop_rarity_percentages"),
            ("profiles", "profiles"),
            ("target_evaluation", "target_evaluation"),
        ),
    )


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
) -> dict[str, Any]:
    optional = optional_fields or set()
    payload = getattr(row, "payload", None)
    output = dict(payload) if isinstance(payload, dict) else {}
    for json_name, attribute_name in fields:
        value = getattr(row, attribute_name)
        if json_name in optional and value is None and json_name not in output:
            continue
        output[json_name] = value
    return output


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
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContentDatabaseError(f"{context}.{key} must be an integer")
    return value


def _optional_int(source: dict[str, Any], key: str, context: str) -> int | None:
    if key not in source or source[key] is None:
        return None
    return _required_int(source, key, context)


def _required_number(source: dict[str, Any], key: str, context: str) -> float:
    value = _required_value(source, key, context)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ContentDatabaseError(f"{context}.{key} must be a number")
    return float(value)


def _required_bool(source: dict[str, Any], key: str, context: str) -> bool:
    value = _required_value(source, key, context)
    if not isinstance(value, bool):
        raise ContentDatabaseError(f"{context}.{key} must be a boolean")
    return value


def _required_value(source: dict[str, Any], key: str, context: str) -> Any:
    if key not in source:
        raise ContentDatabaseError(f"{context} is missing required field {key}")
    return source[key]
