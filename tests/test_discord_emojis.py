from __future__ import annotations

import struct
import zlib
from dataclasses import replace
from types import SimpleNamespace

import discord

import bot.views.exploration as exploration_view
from bot.services.discord_emoji_service import (
    DiscordEmojiService,
    EmojiCatalog,
    EmojiDefinition,
    EmojiRegistry,
    EmojiRegistryEntry,
    inspect_image_file,
    load_emoji_catalog,
    validate_emoji_file,
)
from bot.services.potion_service import PotionInventoryEntry, PotionService
from bot.views.exploration import DefenseLevelSelectView, PotionConsumeSelect, _add_potion_inventory_fields, _potion_inventory_line
from scripts.sync_assets import prepare_emoji_assets


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
