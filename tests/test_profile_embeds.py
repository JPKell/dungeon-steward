from __future__ import annotations

from datetime import UTC, datetime

from bot.models import Player
from bot.services.energy_service import EnergyState
from bot.services.equipment_service import CombatStats
from bot.utils.profile_embeds import build_profile_embed
from bot.utils.time import discord_relative_timestamp


class StubEmojiService:
    def markdown_for(self, asset_key: str | None) -> str | None:
        return {
            "equipment.weapon_blade": "<:blade:1>",
            "equipment.trinket_compass": "<:compass:2>",
            "misc.good": "<:good:3>",
            "misc.evil": "<:evil:4>",
        }.get(asset_key)


def test_profile_embed_groups_combat_and_explore_sections() -> None:
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Scout",
        explore_level=4,
        combat_level=7,
        combat_xp=12,
        combat_xp_to_next_level=50,
        gold=345,
        current_hp=42,
        max_hp=50,
        unspent_stat_points=3,
        total_explorations=14,
        successful_explorations=9,
        discoveries_found=5,
        hero_influence=6,
        villain_influence=4,
        is_defending=True,
        defense_selected_dungeon_level=3,
    )
    state = EnergyState(
        energy=8,
        next_energy_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        full_energy_at=datetime(2026, 7, 3, 17, 0, tzinfo=UTC),
        seconds_until_next=900,
        seconds_until_full=15_300,
    )
    stats = CombatStats(max_hp=55, attack=10, defense=11, speed=12)

    response = build_profile_embed(
        display_name="Scout",
        player=player,
        energy_state=state,
        stats=stats,
        emoji_service=StubEmojiService(),
    )

    assert response.description == "Corridor Scout\n<:blade:1> **Combat - Level 7** <:blade:1>"
    assert [field.name for field in response.fields] == [
        "HP",
        "Gold",
        "XP",
        "ATK",
        "DEF",
        "SPD",
        "Unspent Stat Points",
        "\u200b",
        "Explorations",
        "Discoveries",
        "Influence",
        "Energy",
        "Next Energy",
        "Full Energy",
        "Regeneration",
        "Defending",
    ]
    assert response.fields[0].value == "42/55"
    assert response.fields[1].value == "345"
    assert response.fields[2].value == "12/50"
    assert response.fields[3].value == "10"
    assert response.fields[4].value == "11"
    assert response.fields[5].value == "12"
    assert response.fields[6].value == "3"
    assert response.fields[7].value == "<:compass:2> **Explore - Level 4** <:compass:2>"
    assert response.fields[8].value == "14"
    assert response.fields[9].value == "5"
    assert response.fields[10].value == "<:good:3> 6 : <:evil:4> 4"
    assert response.fields[11].value == "8/12"
    assert response.fields[12].value == discord_relative_timestamp(state.next_energy_at)
    assert response.fields[13].value == discord_relative_timestamp(state.full_energy_at)
    assert response.fields[14].value == "1 energy every 1 hour 57 minutes"
    assert response.fields[14].inline is False
    assert response.fields[-1].value == "Dungeon Level 3"


def test_profile_embed_hides_zero_unspent_stat_points() -> None:
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Scout",
        explore_level=1,
        combat_level=1,
        combat_xp=0,
        combat_xp_to_next_level=25,
        gold=20,
        current_hp=10,
        max_hp=10,
        unspent_stat_points=0,
        total_explorations=0,
        successful_explorations=0,
        discoveries_found=0,
        hero_influence=0,
        villain_influence=0,
    )
    state = EnergyState(
        energy=12,
        next_energy_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        full_energy_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        seconds_until_next=0,
        seconds_until_full=0,
    )
    stats = CombatStats(max_hp=10, attack=5, defense=5, speed=5)

    response = build_profile_embed(
        display_name="Scout",
        player=player,
        energy_state=state,
        stats=stats,
        emoji_service=StubEmojiService(),
    )

    assert "Unspent Stat Points" not in [field.name for field in response.fields]
    assert response.description == "Dungeon Visitor\n<:blade:1> **Combat - Level 1** <:blade:1>"
    explore_header = next(field for field in response.fields if field.name == "\u200b")
    assert explore_header.value == "<:compass:2> **Explore - Level 1** <:compass:2>"
    fields = {field.name: field for field in response.fields}
    assert fields["Energy"].value == "12/12"
    assert fields["Next Energy"].value == discord_relative_timestamp(state.next_energy_at)
    assert fields["Full Energy"].value == discord_relative_timestamp(state.full_energy_at)
    assert fields["Regeneration"].value == "1 energy every 2 hours"
