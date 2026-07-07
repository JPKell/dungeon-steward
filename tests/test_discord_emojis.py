from __future__ import annotations

import struct
import zlib
from dataclasses import replace
from types import SimpleNamespace

import discord

import bot.views.exploration as exploration_view
from bot.models import Player
from bot.services.discord_emoji_service import (
    AssetConfigError,
    DiscordEmojiService,
    EmojiCatalog,
    EmojiDefinition,
    EmojiRegistry,
    EmojiRegistryEntry,
    inspect_image_file,
    load_emoji_catalog,
    validate_emoji_asset_references,
    validate_emoji_file,
)
from bot.services.equipment_service import EquipmentItem
from bot.services.potion_service import PotionInventoryEntry, PotionService
from bot.services.shop_service import ShopService, ShopStock
from bot.views.exploration import DefenseLevelSelectView, PotionConsumeSelect, _add_potion_inventory_fields, _potion_inventory_line
from scripts.sync_assets import plan_emoji_sync, prepare_emoji_assets


def test_emoji_catalog_defaults_and_source_preparation(tmp_path) -> None:
    project = tmp_path / "project"
    (project / "bot/content").mkdir(parents=True)
    source = project / "assets/discord/source/rune_source.png"
    output = project / "assets/discord/emojis/items/runes/rune_01.png"
    source.parent.mkdir(parents=True)
    _write_png(source, 300, 180)
    catalog_path = project / "bot/content/emoji_assets.json"
    catalog_path.write_text(
        """
{
  "version": 1,
  "emojis": {
    "item.rune.01": {
      "name": "ds_rune_01",
      "path": "assets/discord/emojis/items/runes/rune_01.png",
      "source_path": "assets/discord/source/rune_source.png"
    }
  }
}
""",
        encoding="utf-8",
    )

    catalog = load_emoji_catalog(catalog_path, asset_root=project / "assets/discord")
    definition = catalog.get("item.rune.01")

    assert definition.alt_text == "ds rune 01"
    assert definition.required is False
    prepare_emoji_assets([definition])
    validate_emoji_file(definition)
    assert inspect_image_file(output).width == 128


def test_emoji_catalog_generates_equipment_definitions_from_image_assets(tmp_path) -> None:
    project = tmp_path / "project"
    (project / "bot/content").mkdir(parents=True)
    source = project / "assets/discord/source/equipment/weapon_axe.png"
    _write_png(source, 300, 180)
    catalog_path = project / "bot/content/emoji_assets.json"
    image_catalog = {
        "version": 1,
        "assets": {
            "equipment.weapon_axe": {
                "type": "thumbnail",
                "path": "assets/discord/thumbnails/equipment/weapon_axe.webp",
                "source_path": "assets/discord/source/equipment/weapon_axe.png",
            }
        },
    }

    catalog = load_emoji_catalog(
        catalog_path,
        asset_root=project / "assets/discord",
        document={"version": 1, "emojis": {}},
        image_catalog_document=image_catalog,
    )
    definition = catalog.get("equipment.weapon_axe")

    assert definition.name == "ds_eq_weapon_axe"
    assert definition.path == project / "assets/discord/emojis/equipment/weapon_axe.png"
    assert definition.source_path == source
    assert definition.alt_text == "Equipment weapon axe"
    prepare_emoji_assets([definition])
    validate_emoji_file(definition)

    planned, summary = plan_emoji_sync(catalog, EmojiRegistry(version=1, emojis={}), prefix="equipment.")

    assert inspect_image_file(definition.path).width == 128
    assert summary.uploaded == 1
    assert planned[0].definition.key == "equipment.weapon_axe"


def test_equipment_thumbnail_assets_validate_against_generated_emoji_catalog(tmp_path) -> None:
    project = tmp_path / "project"
    content_dir = project / "bot/content"
    content_dir.mkdir(parents=True)
    (content_dir / "equipment.json").write_text(
        '[{"key":"rusty_axe","thumbnail_asset":"equipment.weapon_axe"}]',
        encoding="utf-8",
    )
    catalog = load_emoji_catalog(
        content_dir / "emoji_assets.json",
        asset_root=project / "assets/discord",
        document={"version": 1, "emojis": {}},
        image_catalog_document={
            "version": 1,
            "assets": {
                "equipment.weapon_axe": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/equipment/weapon_axe.webp",
                    "source_path": "assets/discord/source/equipment/weapon_axe.png",
                }
            },
        },
    )

    validate_emoji_asset_references(catalog, content_dir)


def test_equipment_thumbnail_asset_validation_reports_missing_emoji(tmp_path) -> None:
    content_dir = tmp_path / "bot/content"
    content_dir.mkdir(parents=True)
    (content_dir / "equipment.json").write_text(
        '[{"key":"rusty_axe","thumbnail_asset":"equipment.weapon_axe"}]',
        encoding="utf-8",
    )
    catalog = EmojiCatalog(version=1, emojis={})

    try:
        validate_emoji_asset_references(catalog, content_dir)
    except AssetConfigError as error:
        assert "equipment.weapon_axe" in str(error)
    else:
        raise AssertionError("Expected missing equipment emoji reference")


def _write_png(path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(height):
        line = bytearray()
        for x in range(width):
            line.extend(((x + y) % 255, (x * 2) % 255, (y * 3) % 255))
        rows.append(bytes(line))
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(raw, 9))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


def test_potion_inventory_line_uses_registered_custom_emoji(tmp_path) -> None:
    service = PotionService()
    item = service.content.get("potion_max_hp_02")
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiDefinition(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    path=tmp_path / "hp_02.png",
                    alt_text="HP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiRegistryEntry(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    entry = PotionInventoryEntry(stack=SimpleNamespace(quantity=1), item=item)

    assert _potion_inventory_line(service, entry, emoji_service).startswith("<:ds_p_hp_02:123456789>")


def test_potion_select_option_uses_registered_custom_emoji(tmp_path) -> None:
    service = PotionService()
    item = service.content.get("potion_max_hp_02")
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiDefinition(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    path=tmp_path / "hp_02.png",
                    alt_text="HP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiRegistryEntry(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    entry = PotionInventoryEntry(stack=SimpleNamespace(quantity=3), item=item)

    select = PotionConsumeSelect((entry,), emoji_service=emoji_service)

    assert select.options[0].label == "Ironberry Draught x3"
    assert select.options[0].emoji is not None
    assert select.options[0].emoji.name == "ds_p_hp_02"
    assert select.options[0].emoji.id == 123456789


def test_shop_select_option_uses_registered_custom_equipment_emoji(tmp_path) -> None:
    item = EquipmentItem(
        key="rusty-axe",
        name="Rusty Axe",
        slot="weapon",
        rarity="common",
        min_level=1,
        max_level=10,
        cost=60,
        hp=1,
        attack=3,
        defense=0,
        speed=1,
        thumbnail_asset="equipment.weapon_axe",
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=exploration_view.utc_now(),
        refreshes_at=exploration_view.utc_now(),
        items=(item,),
    )
    player = Player(discord_user_id=1, guild_id=10, display_name="Shopper", gold=250)
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "equipment.weapon_axe": EmojiDefinition(
                    key="equipment.weapon_axe",
                    name="ds_eq_weapon_axe",
                    path=tmp_path / "weapon_axe.png",
                    alt_text="Weapon axe",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "equipment.weapon_axe": EmojiRegistryEntry(
                    key="equipment.weapon_axe",
                    name="ds_eq_weapon_axe",
                    emoji_id="987654321",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )

    view = exploration_view.ShopView(
        session_factory=object(),
        exploration_service=object(),
        defense_service=object(),
        shop_service=ShopService(),
        owner_user_id=1,
        stock=stock,
        player=player,
        emoji_service=emoji_service,
    )
    select = next(child for child in view.children if isinstance(child, discord.ui.Select))

    assert select.options[0].label == "Rusty Axe"
    assert select.options[0].emoji is not None
    assert select.options[0].emoji.name == "ds_eq_weapon_axe"
    assert select.options[0].emoji.id == 987654321


def test_dungeon_potion_select_uses_registered_custom_emoji(tmp_path, monkeypatch) -> None:
    service = PotionService()
    item = service.content.get("potion_max_hp_02")
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiDefinition(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    path=tmp_path / "hp_02.png",
                    alt_text="HP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiRegistryEntry(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    entry = PotionInventoryEntry(stack=SimpleNamespace(quantity=3), item=item)
    monkeypatch.setattr(exploration_view, "DEFAULT_DISCORD_EMOJIS", emoji_service)

    view = DefenseLevelSelectView(
        session_factory=object(),
        exploration_service=object(),
        defense_service=object(),
        shop_service=object(),
        owner_user_id=1,
        options=[discord.SelectOption(label="Level 1", value="1")],
        potion_entries=(entry,),
    )
    potion_select = [child for child in view.children if isinstance(child, discord.ui.Select)][1]

    assert potion_select.options[0].label == "Ironberry Draught x3"
    assert "❤️" not in potion_select.options[0].label
    assert potion_select.options[0].emoji is not None
    assert potion_select.options[0].emoji.name == "ds_p_hp_02"
    assert potion_select.options[0].emoji.id == 123456789


def test_dungeon_potion_page_uses_inventory_custom_emoji_line(tmp_path) -> None:
    service = PotionService()
    item = service.content.get("potion_max_hp_02")
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiDefinition(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    path=tmp_path / "hp_02.png",
                    alt_text="HP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiRegistryEntry(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    entry = PotionInventoryEntry(stack=SimpleNamespace(quantity=3), item=item)
    response = discord.Embed(title="Choose Defense Level")

    _add_potion_inventory_fields(response, potion_service=service, entries=(entry,), emoji_service=emoji_service)

    fields = {field.name: field.value for field in response.fields}
    assert fields["Owned Potions"].startswith("<:ds_p_hp_02:123456789> **Ironberry Draught** x3")
    assert "❤️" not in fields["Owned Potions"]


def test_potion_inventory_line_uses_runtime_default_emoji_service(tmp_path, monkeypatch) -> None:
    service = PotionService()
    item = service.content.get("potion_max_hp_02")
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiDefinition(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    path=tmp_path / "hp_02.png",
                    alt_text="HP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiRegistryEntry(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    entry = PotionInventoryEntry(stack=SimpleNamespace(quantity=1), item=item)

    monkeypatch.setattr(exploration_view, "DEFAULT_DISCORD_EMOJIS", emoji_service)

    assert _potion_inventory_line(service, entry).startswith("<:ds_p_hp_02:123456789>")


def test_potion_inventory_line_derives_emoji_key_for_stale_potion_content(tmp_path) -> None:
    service = PotionService()
    item = replace(service.content.get("potion_max_hp_02"), thumbnail_asset=None)
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiDefinition(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    path=tmp_path / "hp_02.png",
                    alt_text="HP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.max_hp.02": EmojiRegistryEntry(
                    key="item.potion.max_hp.02",
                    name="ds_p_hp_02",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    entry = PotionInventoryEntry(stack=SimpleNamespace(quantity=1), item=item)

    assert _potion_inventory_line(service, entry, emoji_service).startswith("<:ds_p_hp_02:123456789>")
