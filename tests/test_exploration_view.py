from __future__ import annotations

import random
from datetime import UTC, datetime
from types import SimpleNamespace

import discord
import pytest

from bot.models import Player
from bot.services.equipment_service import EquipmentItem
from bot.services.potion_service import PotionInventoryEntry, PotionService
from bot.services.shop_service import ShopService, ShopStock
from bot.views.exploration import (
    STAT_ALLOCATION_PROFILE,
    DefenseLevelSelectView,
    ExplorationView,
    ExploreLevelSelectView,
    PostExplorationView,
    PotionInventoryView,
    ShopView,
    StewardsHallView,
    _dungeon_select_options,
    _stat_allocation_summary_embed,
    build_hall_embed,
)


class DummyChoice:
    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label


class DummyEncounter:
    def __init__(self, choices: list[DummyChoice]) -> None:
        self.choices = choices


class DummySessionFactory:
    pass


class DummyDefenseService:
    pass


class DummyShopService:
    pass


class DummyExplorationService:
    pass


class DummySession:
    def commit(self) -> None:
        pass


class DummySessionContext:
    def __enter__(self) -> DummySession:
        return DummySession()

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass


class DummyContextSessionFactory:
    def __call__(self) -> DummySessionContext:
        return DummySessionContext()


def test_exploration_choices_are_shuffled(monkeypatch: pytest.MonkeyPatch) -> None:
    choices = [
        DummyChoice("hero", "Heroic Action"),
        DummyChoice("villain", "Villainous Action"),
        DummyChoice("destabilize", "Destabilize Action"),
    ]
    encounter = DummyEncounter(choices)

    monkeypatch.setattr(random, "shuffle", lambda x: x.reverse())

    view = ExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        resolution_key="test-key",
        owner_user_id=1,
        encounter=encounter,
    )

    assert [button.label for button in view.children if isinstance(button, discord.ui.Button)] == [
        "Destabilize Action",
        "Villainous Action",
        "Heroic Action",
    ]


def test_action_view_can_include_stat_allocation_buttons() -> None:
    view = PostExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        stat_allocation_context=STAT_ALLOCATION_PROFILE,
    )

    assert [button.label for button in view.children if isinstance(button, discord.ui.Button)] == [
        "Explore",
        "Defend",
        "Shop",
        "Steward's Hall",
        "ATK +1",
        "DEF +1",
        "SPD +1",
    ]


def test_defending_action_view_keeps_return_button_by_default() -> None:
    view = PostExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        is_defending=True,
    )

    labels = [button.label for button in view.children if isinstance(button, discord.ui.Button)]

    assert "Return from Dungeon" in labels
    assert "Defend" not in labels
    assert labels == ["Explore", "Return from Dungeon", "Shop", "Steward's Hall"]


def test_defending_result_view_can_suppress_return_button() -> None:
    view = PostExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        is_defending=True,
        allow_defense_return_button=False,
    )

    labels = [button.label for button in view.children if isinstance(button, discord.ui.Button)]

    assert "Return from Dungeon" not in labels
    assert "Defend" not in labels
    assert labels == ["Explore", "Shop", "Steward's Hall"]


@pytest.mark.asyncio
async def test_resolving_defense_before_explore_stops_before_starting_exploration() -> None:
    report = SimpleNamespace(
        dungeon_level=1,
        reason="exploring",
        elapsed_seconds=60,
        capped_seconds=60,
        scheduled_battles=1,
        completed_battles=1,
        unresolved_attacks=0,
        victories=1,
        defeats=0,
        draws=0,
        combat_xp_earned=10,
        gold_earned=5,
        combat_levels_gained=0,
        stat_points_earned=0,
        starting_hp=10,
        ending_hp=8,
        max_hp=10,
        potion_effects=(),
        potion_healing=0,
        potion_luck_procs=0,
        potion_bonus_combat_xp=0,
        max_hp_effect_expired=False,
        enemies_encountered={"Slime": 1},
        notable_battles=(),
    )

    class ResolvingDefenseService:
        def resolve_before_explore(self, *_args, **_kwargs):
            return report

    sent_messages: list[dict[str, object]] = []

    class Followup:
        async def send(self, **kwargs) -> None:
            sent_messages.append(kwargs)

    interaction = SimpleNamespace(
        guild_id=10,
        user=SimpleNamespace(id=1, display_name="Scout"),
        followup=Followup(),
    )
    view = PostExplorationView(
        session_factory=DummyContextSessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=ResolvingDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        is_defending=True,
    )

    should_continue = await view.resolve_defense_before_explore(interaction)

    assert not should_continue
    assert len(sent_messages) == 1
    report_view = sent_messages[0]["view"]
    labels = [button.label for button in report_view.children if isinstance(button, discord.ui.Button)]
    assert labels == ["Explore", "Defend", "Steward's Hall"]


def test_dungeon_level_selectors_do_not_include_return_buttons() -> None:
    options = [discord.SelectOption(label="Level 1", value="1")]
    explore = ExploreLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=options,
        is_defending=True,
    )
    defense = DefenseLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=options,
        is_defending=True,
    )

    for view in (explore, defense):
        labels = [button.label for button in view.children if isinstance(button, discord.ui.Button)]
        assert "Return from Dungeon" not in labels
        assert "Stop Defending" not in labels
        assert "Defend" not in labels


def test_dungeon_level_options_show_unlocked_levels_and_first_locked_only() -> None:
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Test Player",
        highest_unlocked_dungeon_level=3,
    )

    options = _dungeon_select_options(player)

    assert [option.label for option in options] == ["Level 1", "Level 2", "Level 3", "Level 4 locked"]


def test_hall_embed_uses_community_dungeon_details_without_action_list() -> None:
    dungeon = SimpleNamespace(
        level=4,
        gold=1200,
        hero_influence=7,
        villain_influence=3,
        stability=82,
    )
    objective = SimpleNamespace(
        title="Map the Moving Halls",
        description="Complete 100 explorations.",
        progress_value=17,
        target_value=100,
        ends_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
    )

    hall = build_hall_embed(dungeon=dungeon, objective=objective)
    fields = {field.name: field.value for field in hall.fields}

    assert hall.title == "Steward's Hall"
    assert hall.description is not None
    assert "dungeon's nerve center" in hall.description
    assert "Available Actions" not in fields
    assert hall.fields[0].name == "\u200b"
    assert hall.fields[0].value == "**Shared community dungeon**"
    assert fields["Level"] == "4"
    assert fields["Gold"] == "1200"
    assert fields["Hero / Villain Influence"] == "7 : 3"
    assert fields["Stability"] == "82/100"
    assert fields["Weekly Objective: Map the Moving Halls"].splitlines()[0] == "Complete 100 explorations."
    assert fields["Weekly Objective: Map the Moving Halls"].splitlines()[1].startswith("Progress: 17/100 (17%) | Ends <t:")
    assert "Weekly Objective" not in fields
    assert "Progress" not in fields
    assert [field.name for field in hall.fields[:7]] == [
        "\u200b",
        "Level",
        "Gold",
        "\u200b",
        "Hero / Villain Influence",
        "Stability",
        "Weekly Objective: Map the Moving Halls",
    ]


def test_stat_allocation_summary_ignores_image_only_banner_embed() -> None:
    banner = discord.Embed()
    banner.set_image(url="attachment://banner.png")
    content = discord.Embed(title="Profile")
    content.add_field(name="Level", value="3")
    interaction = SimpleNamespace(message=SimpleNamespace(embeds=[banner, content]))

    response = _stat_allocation_summary_embed(interaction, stat="attack", remaining_points=2)

    assert response.title == "Profile"
    assert response.image.url is None
    assert any(field.name == "Stat Allocation" for field in response.fields)


def test_hall_keeps_inventory_button_but_defense_selector_uses_potion_dropdown() -> None:
    hall = StewardsHallView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
    )
    defense = DefenseLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=[discord.SelectOption(label="Level 1", value="1")],
    )

    hall_labels = [button.label for button in hall.children if isinstance(button, discord.ui.Button)]

    assert "Inventory" in hall_labels
    assert "Dungeon" not in hall_labels
    assert "Inventory" not in [button.label for button in defense.children if isinstance(button, discord.ui.Button)]


def test_dungeon_level_selector_lists_owned_potions_with_emoji_and_quantity() -> None:
    service = PotionService()
    entries = (
        PotionInventoryEntry(
            stack=SimpleNamespace(quantity=3),
            item=service.content.get("potion_max_hp_02"),
        ),
    )

    defense = DefenseLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=[discord.SelectOption(label="Level 1", value="1")],
        potion_entries=entries,
    )

    selects = [child for child in defense.children if isinstance(child, discord.ui.Select)]
    potion_select = selects[1]

    assert len(selects) == 2
    assert potion_select.placeholder == "Consume a potion"
    assert potion_select.options[0].label.endswith("Ironberry Draught x3")
    if potion_select.options[0].emoji is not None:
        assert "❤️" not in potion_select.options[0].label


def test_potion_inventory_select_is_capped_to_owned_items() -> None:
    service = PotionService()
    entries = tuple(
        PotionInventoryEntry(stack=SimpleNamespace(quantity=1), item=item)
        for item in service.content.items[:30]
    )

    view = PotionInventoryView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        origin="hall",
        entries=entries,
    )
    select = next(child for child in view.children if isinstance(child, discord.ui.Select))

    assert len(select.options) == 25


def test_shop_view_uses_dropdown_and_confirm_button() -> None:
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
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(item,),
    )
    player = Player(discord_user_id=1, guild_id=10, display_name="Test Player", gold=250)

    view = ShopView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=ShopService(),
        owner_user_id=1,
        stock=stock,
        player=player,
    )

    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]
    select = next(child for child in view.children if isinstance(child, discord.ui.Select))

    assert len(select.options) == 1
    assert select.placeholder == "Browse Shop"
    assert "Price 🪙 60" in (select.options[0].description or "")
    assert all(button.label not in {str(number) for number in range(1, 11)} for button in buttons)
    assert "Explore" in [button.label for button in buttons]
    assert "Defend" in [button.label for button in buttons]
    assert next(button for button in buttons if button.label == "Back").row == 2
    assert "Buy Selected" not in [button.label for button in buttons]

    selected_view = ShopView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=ShopService(),
        owner_user_id=1,
        stock=stock,
        player=player,
        selected_stock_number=1,
    )

    selected_buttons = [child for child in selected_view.children if isinstance(child, discord.ui.Button)]
    selected_select = next(child for child in selected_view.children if isinstance(child, discord.ui.Select))

    assert "Buy Selected" in [button.label for button in selected_buttons]
    assert selected_select.options[0].default

    defending_view = ShopView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=ShopService(),
        owner_user_id=1,
        stock=stock,
        player=player,
        is_defending=True,
    )
    defending_labels = [button.label for button in defending_view.children if isinstance(button, discord.ui.Button)]

    assert "Explore" in defending_labels
    assert "Return from Dungeon" in defending_labels
    assert "Defend" not in defending_labels


def test_shop_view_hides_owned_equipment_from_dropdown() -> None:
    owned_item = EquipmentItem(
        key="heroic-blade",
        name="Heroic Blade",
        slot="weapon",
        rarity="legendary",
        min_level=1,
        max_level=10,
        cost=140,
        hp=4,
        attack=8,
        defense=3,
        speed=2,
    )
    available_item = EquipmentItem(
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
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(available_item, owned_item),
    )
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Test Player",
        gold=250,
        weapon=owned_item.key,
    )

    view = ShopView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=ShopService(),
        owner_user_id=1,
        stock=stock,
        player=player,
    )

    select = next(child for child in view.children if isinstance(child, discord.ui.Select))

    assert [option.label for option in select.options] == ["Rusty Axe"]
