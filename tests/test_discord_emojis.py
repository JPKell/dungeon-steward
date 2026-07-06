from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import bot.views.exploration as exploration_view
from bot.services.discord_emoji_service import (
    DiscordEmojiService,
    EmojiCatalog,
    EmojiDefinition,
    EmojiRegistry,
    EmojiRegistryEntry,
)
from bot.services.potion_service import PotionInventoryEntry, PotionService
from bot.views.exploration import _potion_inventory_line


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
