from __future__ import annotations

from bot.models import GuildDungeon


def clamp_stability(value: int) -> int:
    return max(0, min(100, value))


class GuildDungeonService:
    def apply_choice(
        self,
        dungeon: GuildDungeon,
        *,
        gold: int,
        hero_effect: int,
        villain_effect: int,
        stability_effect: int,
        discovery_category: str | None = None,
    ) -> None:
        dungeon.gold += max(0, gold // 2)
        dungeon.hero_influence += hero_effect
        dungeon.villain_influence += villain_effect
        dungeon.stability = clamp_stability(dungeon.stability + stability_effect)
        dungeon.total_explorations += 1
        if hero_effect < 0:
            dungeon.heroes_defeated += abs(hero_effect)
        if discovery_category and discovery_category.lower() in {"room", "rooms", "strange rooms"}:
            dungeon.rooms_discovered += 1
        if dungeon.total_explorations and dungeon.total_explorations % 50 == 0:
            dungeon.level += 1

