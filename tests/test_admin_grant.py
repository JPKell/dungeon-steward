from __future__ import annotations

import discord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bot.commands.admin import AdminGrantBrowserView, AdminPlayerInspectView, _grant_direct_reward
from bot.models import Player, PotionInventoryStack
from bot.services.discord_emoji_service import (
    DiscordEmojiService,
    EmojiCatalog,
    EmojiDefinition,
    EmojiRegistry,
    EmojiRegistryEntry,
)
from bot.services.energy_service import EnergyService
from bot.services.equipment_service import EquipmentService
from bot.services.player_service import PlayerService
from bot.services.potion_service import PotionService
from tests.conftest import make_player


def test_admin_direct_grant_updates_core_player_resources(db: Session, now) -> None:
    player = make_player(db, now=now)
    energy = EnergyService()

    _grant_direct_reward(player, "gold", 25, energy)
    _grant_direct_reward(player, "explore_xp", 500, energy)
    _grant_direct_reward(player, "combat_xp", player.combat_xp_to_next_level, energy)
    _grant_direct_reward(player, "attack", 3, energy)

    assert player.gold == 25
    assert player.experience == 500
    assert player.explore_level > 1
    assert player.combat_level == 2
    assert player.unspent_stat_points > 0
    assert player.attack >= 4


def test_admin_potion_picker_filters_and_grants_stack(session_factory: sessionmaker[Session]) -> None:
    view = AdminGrantBrowserView(
        session_factory=session_factory,
        invoker_user_id=99,
        target_user_id=123,
        target_display_name="Potion Tester",
        guild_id=10,
        grant_kind="potion",
        amount=3,
        players=PlayerService(),
        energy=EnergyService(),
        potions=PotionService(),
    )

    view.set_category("xp")

    assert view._page_items()
    assert all(item.effect_group == "xp" for item in view._page_items())

    result = view._grant_potion("potion_xp_01")

    with session_factory() as db:
        player = db.scalar(select(Player).where(Player.discord_user_id == 123, Player.guild_id == 10))
        assert player is not None
        stack = db.scalar(
            select(PotionInventoryStack).where(
                PotionInventoryStack.player_id == player.id,
                PotionInventoryStack.item_key == "potion_xp_01",
            )
        )
        assert stack is not None
        assert stack.quantity == 3
    assert result.title == "Potion Granted"


def test_admin_potion_picker_uses_registered_custom_emoji(session_factory: sessionmaker[Session], tmp_path) -> None:
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.xp.01": EmojiDefinition(
                    key="item.potion.xp.01",
                    name="ds_p_xp_01",
                    path=tmp_path / "xp_01.png",
                    alt_text="XP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.xp.01": EmojiRegistryEntry(
                    key="item.potion.xp.01",
                    name="ds_p_xp_01",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    view = AdminGrantBrowserView(
        session_factory=session_factory,
        invoker_user_id=99,
        target_user_id=123,
        target_display_name="Potion Tester",
        guild_id=10,
        grant_kind="potion",
        amount=3,
        players=PlayerService(),
        energy=EnergyService(),
        potions=PotionService(),
        emoji_service=emoji_service,
    )

    item = view.potions.content.get("potion_xp_01")
    option = view.option_for(item)
    page_line = view._line_for(1, item)

    assert page_line.startswith("1. <:ds_p_xp_01:123456789> Scholar's Sip")
    assert "📘" not in page_line
    assert isinstance(option.emoji, discord.PartialEmoji)
    assert option.emoji.name == "ds_p_xp_01"
    assert option.emoji.id == 123456789


def test_admin_grant_browser_splits_long_page_fields_for_potions_and_equipment(
    session_factory: sessionmaker[Session],
) -> None:
    for grant_kind, services in (
        ("potion", {"potions": PotionService()}),
        ("equipment", {"equipment": EquipmentService()}),
    ):
        view = AdminGrantBrowserView(
            session_factory=session_factory,
            invoker_user_id=99,
            target_user_id=123,
            target_display_name="Grant Tester",
            guild_id=10,
            grant_kind=grant_kind,
            amount=3,
            players=PlayerService(),
            energy=EnergyService(),
            **services,
        )

        def long_line(index, item) -> str:
            return f"{index}. {item.name} " + ("x" * 180)

        view._line_for = long_line
        response = view.build_embed()
        page_fields = [field for field in response.fields if field.name.startswith("Page")]

        assert len(page_fields) > 1
        assert all(len(field.value) <= 1024 for field in response.fields)


def test_admin_grant_browser_real_catalog_fields_fit_discord_limit(
    session_factory: sessionmaker[Session],
) -> None:
    for grant_kind, services in (
        ("potion", {"potions": PotionService()}),
        ("equipment", {"equipment": EquipmentService()}),
    ):
        view = AdminGrantBrowserView(
            session_factory=session_factory,
            invoker_user_id=99,
            target_user_id=123,
            target_display_name="Grant Tester",
            guild_id=10,
            grant_kind=grant_kind,
            amount=3,
            players=PlayerService(),
            energy=EnergyService(),
            **services,
        )

        for category, _label in view._categories():
            view.set_category(category)
            for page in range(view._page_count()):
                view.page = page
                view._refresh_components()
                response = view.build_embed()

                assert all(len(field.value) <= 1024 for field in response.fields)


def test_admin_player_inspect_view_builds_profile_potions_and_equipment_pages(
    session_factory: sessionmaker[Session],
    now,
    tmp_path,
) -> None:
    equipment = EquipmentService()
    item = next(item for item in equipment.items if item.slot == "weapon" and item.description)
    potions = PotionService()
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "item.potion.xp.01": EmojiDefinition(
                    key="item.potion.xp.01",
                    name="ds_p_xp_01",
                    path=tmp_path / "xp_01.png",
                    alt_text="XP potion",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "item.potion.xp.01": EmojiRegistryEntry(
                    key="item.potion.xp.01",
                    name="ds_p_xp_01",
                    emoji_id="123456789",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
            },
        ),
    )
    with session_factory() as db:
        player = make_player(db, now=now, user_id=321, guild_id=10)
        player.weapon = item.key
        potions.add_drop(db, player, "potion_xp_01", amount=2)
        db.commit()

    view = AdminPlayerInspectView(
        session_factory=session_factory,
        invoker_user_id=99,
        target_user_id=321,
        target_display_name="Inspect Target",
        guild_id=10,
        energy=EnergyService(),
        equipment=equipment,
        potions=potions,
        emoji_service=emoji_service,
    )

    profile = view.build_embed()
    view.set_page("potions")
    potion_inventory = view.build_embed()
    view.set_page("equipment")
    equipment_page = view.build_embed()

    assert profile.title == "Inspect Target"
    assert profile.footer.text == "Admin inspect | Profile"
    assert potion_inventory.title == "Inspect Target's Potion Inventory"
    assert "<:ds_p_xp_01:123456789>" in {field.name: field.value for field in potion_inventory.fields}["Owned Potions"]
    assert equipment_page.title == "Inspect Target's Equipment"
    assert equipment_page.footer.text == "Admin inspect | Equipment"
    equipment_fields = {field.name: field.value for field in equipment_page.fields}
    weapon_value = equipment_fields["⚔️ Weapon"]
    assert item.name in weapon_value
    assert item.description not in weapon_value


def test_admin_equipment_picker_filters_and_equips_item(session_factory: sessionmaker[Session], now) -> None:
    equipment = EquipmentService()
    item = next(item for item in equipment.items if item.slot == "weapon")
    with session_factory() as db:
        make_player(db, now=now, user_id=456, guild_id=10)
        db.commit()

    view = AdminGrantBrowserView(
        session_factory=session_factory,
        invoker_user_id=99,
        target_user_id=456,
        target_display_name="Equipment Tester",
        guild_id=10,
        grant_kind="equipment",
        amount=1,
        players=PlayerService(),
        energy=EnergyService(),
        equipment=equipment,
    )

    view.set_category("weapon")

    assert view._page_items()
    assert all(item.slot == "weapon" for item in view._page_items())

    result = view._grant_equipment(item.key)

    with session_factory() as db:
        player = db.scalar(select(Player).where(Player.discord_user_id == 456, Player.guild_id == 10))
        assert player is not None
        assert player.weapon == item.key
    assert result.title == "Equipment Granted"
