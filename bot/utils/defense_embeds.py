from __future__ import annotations

import discord

from bot.services.defense_service import DefenseReport, StartedDefense
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService
from bot.services.discord_emoji_service import DEFAULT_DISCORD_EMOJIS, DiscordEmojiService
from bot.services.enemy_service import DUNGEON_LEVELS, ENEMY_TYPES
from bot.services.location_service import LOCATION_SERVICE
from bot.utils.embeds import DEEP_NAVY, WARM_GOLD, embed
from bot.utils.time import discord_relative_timestamp, human_duration


def build_defense_started_embed(
    started: StartedDefense,
    *,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
) -> discord.Embed:
    response = embed(
        "Defending the Dungeon",
        f"Dungeon Level {started.dungeon_level} is now covered.",
        colour=DEEP_NAVY,
    )
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("defending_the_dungeon"))
    asset_service.apply_thumbnail(response, _dungeon_thumbnail_asset(started.dungeon_level))
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


def build_defense_report_embed(
    report: DefenseReport,
    *,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
    emoji_service: DiscordEmojiService = DEFAULT_DISCORD_EMOJIS,
) -> discord.Embed:
    response = embed(
        "Defense Complete",
        f"Dungeon Level {report.dungeon_level} | Ended by {report.reason}",
        colour=WARM_GOLD,
    )
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("returned_from_dungeon"))
    asset_service.apply_thumbnail(response, _enemy_thumbnail_asset(report.enemies_encountered))
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
            f"Completed: {report.completed_battles}"
        ),
    )
    response.add_field(
        name="Results",
        value=(
            f"Victories: {report.victories}\n"
            f"Defeats: {report.defeats}"
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
    if (
        report.potion_effects
        or report.potion_healing
        or report.potion_luck_procs
        or report.potion_bonus_combat_xp
        or report.max_hp_effect_expired
    ):
        potion_lines: list[str] = []
        if report.potion_effects:
            potion_lines.append("Active: " + ", ".join(report.potion_effects[:6]))
        if report.potion_healing:
            potion_lines.append(f"Healing: {report.potion_healing} HP")
        if report.potion_luck_procs:
            potion_lines.append(f"Luck procs: {report.potion_luck_procs}")
        if report.potion_bonus_combat_xp:
            potion_lines.append(f"Bonus XP: {report.potion_bonus_combat_xp}")
        if report.max_hp_effect_expired:
            potion_lines.append("Max HP effect expired during the defense.")
        response.add_field(name="Potions", value="\n".join(potion_lines), inline=False)
    response.add_field(
        name="Enemies Encountered",
        value=_enemy_summary(report.enemies_encountered, emoji_service),
        inline=False,
    )
    return response


def _enemy_summary(enemies: dict[str, int], emoji_service: DiscordEmojiService = DEFAULT_DISCORD_EMOJIS) -> str:
    if not enemies:
        return "No completed attacks reached the dungeon line."
    ordered = sorted(enemies.items(), key=lambda item: (-item[1], item[0]))
    summary = "\n".join(_enemy_summary_line(name, count, emoji_service) for name, count in ordered[:12])
    if len(ordered) > 12:
        summary += f"\n...and {len(ordered) - 12} more"
    return summary


def _enemy_summary_line(name: str, count: int, emoji_service: DiscordEmojiService) -> str:
    marker = _enemy_marker(name, emoji_service)
    prefix = f"{marker} " if marker else ""
    return f"{prefix}**{name}**: {count}"


def _dungeon_thumbnail_asset(dungeon_level: int) -> str | None:
    config = DUNGEON_LEVELS.get(dungeon_level, {})
    value = config.get("thumbnail_asset")
    return value if isinstance(value, str) and value else None


def _enemy_thumbnail_asset(enemies: dict[str, int]) -> str | None:
    for name, _count in sorted(enemies.items(), key=lambda item: (-item[1], item[0])):
        value = _enemy_content_by_name(name).get("thumbnail_asset")
        if isinstance(value, str) and value:
            return value
    return None


def _enemy_marker(name: str, emoji_service: DiscordEmojiService) -> str:
    value = _enemy_content_by_name(name).get("emoji_asset")
    if isinstance(value, str) and value:
        return emoji_service.markdown_for(value) or ""
    return ""


def _enemy_content_by_name(name: str) -> dict[str, object]:
    for enemy in ENEMY_TYPES.values():
        if enemy.get("name") == name:
            return enemy
    return {}
