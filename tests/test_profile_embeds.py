from __future__ import annotations

from datetime import UTC, datetime

from bot.models import Player
from bot.services.energy_service import EnergyState
from bot.services.equipment_service import CombatStats
from bot.utils.profile_embeds import build_profile_embed


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
    )

    assert response.description == "Corridor Scout\n⚔️ Combat ⚔️"
    assert [field.name for field in response.fields] == [
        "Level",
        "HP",
        "Gold",
        "ATK",
        "DEF",
        "SPD",
        "XP",
        "Unspent Stat Points",
        "\u200b",
        "Energy",
        "Next Energy",
        "Explorations",
        "Successful",
        "Discoveries",
        "Hero / Villain Influence",
        "Defending",
    ]
    assert response.fields[0].value == "7"
    assert response.fields[1].value == "42/55"
    assert response.fields[2].value == "345"
    assert response.fields[3].value == "10"
    assert response.fields[4].value == "11"
    assert response.fields[5].value == "12"
    assert response.fields[6].value == "12/50"
    assert response.fields[8].value == "**🧭 Explore 🧭**"
    assert response.fields[-2].value == "6 : 4"
    assert response.fields[-1].value == "Dungeon Level 3"
