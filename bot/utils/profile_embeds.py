from __future__ import annotations

import discord

from bot.config import MAX_ENERGY
from bot.models import Player
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService
from bot.services.discord_emoji_service import DEFAULT_DISCORD_EMOJIS, DiscordEmojiService
from bot.services.energy_service import EnergyState
from bot.services.equipment_service import CombatStats
from bot.services.location_service import LOCATION_SERVICE
from bot.services.player_service import title_for_player
from bot.services.progression_service import get_explore_cooldown_minutes
from bot.utils.embeds import WARM_GOLD, embed
from bot.utils.time import discord_relative_timestamp, human_duration
from bot.utils.helpers import influence_value
from bot.utils.emoji import equipment_emoji



def build_profile_embed(
    *,
    display_name: str,
    player: Player,
    energy_state: EnergyState,
    stats: CombatStats,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
    emoji_service: DiscordEmojiService = DEFAULT_DISCORD_EMOJIS,
) -> discord.Embed:
    combat_marker = equipment_emoji("weapon", "blade")
    explore_marker = equipment_emoji("trinket", "compass")
    
    # Title 
    response = embed(display_name,title_for_player(player),colour=WARM_GOLD)

    # Combat section 
    _add_header(response, _section_header(combat_marker, 'Combat', player.combat_level))
    # Combat Stats row 1
    response.add_field(name="HP", value=f"{player.current_hp}/{stats.max_hp}")
    response.add_field(name="Gold", value=str(player.gold))
    response.add_field(name="XP", value=f"{player.combat_xp}/{player.combat_xp_to_next_level}")
    # Combat Stats row 2
    response.add_field(name="ATK", value=str(stats.attack))
    response.add_field(name="DEF", value=str(stats.defense))
    response.add_field(name="SPD", value=str(stats.speed))
    # Unspent Stat Points row 3
    if player.unspent_stat_points > 0:
        response.add_field(name="Unspent Stat Points", value=str(player.unspent_stat_points))
    # Defending row 4
    response.add_field(name="Defending", value=_defending_value(player), inline=False)

    # Explore section
    _add_header(response, _section_header(explore_marker, "Explore", player.explore_level))
    
    # Explore row 1
    response.add_field(name="Explorations", value=str(player.total_explorations))
    response.add_field(name="Discoveries", value=str(player.discoveries_found))
    response.add_field(name="Influence", value=influence_value(player.hero_influence, player.villain_influence, emoji_service))

    # Explore row 2
    response.add_field(name="Energy", value=f"{energy_state.energy}/{MAX_ENERGY}")
    response.add_field(name="Next Energy", value=discord_relative_timestamp(energy_state.next_energy_at))
    response.add_field(name="Full Energy", value=discord_relative_timestamp(energy_state.full_energy_at))
    
    # Regneration row 3
    cooldown_seconds = get_explore_cooldown_minutes(player.explore_level) * 60
    response.add_field(name="Regeneration", value=f"1 energy every {human_duration(cooldown_seconds)}", inline=False)
    
    
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("user_profile"))
    return response


def _section_header(emoji: str, label: str, level: int) -> str:
    return f"{emoji} **{label} - Level {level}** {emoji}"


def _emoji_marker(emoji_service: DiscordEmojiService, asset_key: str, fallback: str) -> str:
    return emoji_service.markdown_for(asset_key) or fallback


def _add_header(response: discord.Embed, name: str) -> None:
    response.add_field(name="\u200b", value=name, inline=False)


def _defending_value(player: Player) -> str:
    if player.is_defending and player.defense_selected_dungeon_level:
        return f"Dungeon Level {player.defense_selected_dungeon_level}"
    return "Not defending"
