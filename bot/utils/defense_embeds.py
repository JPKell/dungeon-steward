from __future__ import annotations

import discord

from bot.services.defense_service import DefenseReport, StartedDefense
from bot.utils.embeds import DEEP_NAVY, WARM_GOLD, embed
from bot.utils.time import discord_relative_timestamp, human_duration


def build_defense_started_embed(started: StartedDefense) -> discord.Embed:
    response = embed(
        "Defending the Dungeon",
        f"Dungeon Level {started.dungeon_level} is now covered.",
        colour=DEEP_NAVY,
    )
    response.add_field(name="HP", value=f"{started.current_hp}/{started.stats.max_hp}")
    response.add_field(
        name="Stats",
        value=(
            f"Attack {started.stats.attack}\n"
            f"Defense {started.stats.defense}\n"
            f"Speed {started.stats.speed}"
        ),
    )
    response.add_field(
        name="Maximum Duration",
        value=discord_relative_timestamp(started.max_ends_at),
        inline=False,
    )
    response.set_footer(text="Defending resolves when you stop, explore, or hit your duration cap.")
    return response


def build_defense_report_embed(report: DefenseReport) -> discord.Embed:
    response = embed(
        "Defense Complete",
        f"Dungeon Level {report.dungeon_level} | Ended by {report.reason}",
        colour=WARM_GOLD,
    )
    response.add_field(
        name="Duration",
        value=(
            f"Actual: {human_duration(report.elapsed_seconds)}\n"
            f"Counted: {human_duration(report.capped_seconds)}"
        ),
    )
    response.add_field(
        name="Battles",
        value=(
            f"Scheduled: {report.scheduled_battles}\n"
            f"Completed: {report.completed_battles}\n"
            f"Unresolved: {report.unresolved_attacks}"
        ),
    )
    response.add_field(
        name="Results",
        value=(
            f"Victories: {report.victories}\n"
            f"Defeats: {report.defeats}\n"
            f"Draws: {report.draws}"
        ),
    )
    response.add_field(
        name="Rewards",
        value=f"{report.combat_xp_earned} Combat XP\n{report.gold_earned} gold",
    )
    response.add_field(
        name="Combat Growth",
        value=(
            f"Levels gained: {report.combat_levels_gained}\n"
            f"Stat points gained: {report.stat_points_earned}"
        ),
    )
    response.add_field(
        name="HP",
        value=f"Started: {report.starting_hp}\nEnded: {report.ending_hp}/{report.max_hp}",
    )
    response.add_field(
        name="Enemies Encountered",
        value=_enemy_summary(report.enemies_encountered),
        inline=False,
    )
    if report.notable_battles:
        response.add_field(name="Notable Battles", value="\n".join(report.notable_battles), inline=False)
    return response


def _enemy_summary(enemies: dict[str, int]) -> str:
    if not enemies:
        return "No completed attacks reached the dungeon line."
    ordered = sorted(enemies.items(), key=lambda item: (-item[1], item[0]))
    summary = "\n".join(f"{name}: {count}" for name, count in ordered[:12])
    if len(ordered) > 12:
        summary += f"\n...and {len(ordered) - 12} more"
    return summary
