from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bot.commands.admin import AdminGrantBrowserView, _grant_direct_reward
from bot.models import Player, PotionInventoryStack
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
