from __future__ import annotations

import discord

from bot.config import MAX_ENERGY
from bot.models import Player
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService
from bot.services.energy_service import EnergyState
from bot.services.equipment_service import CombatStats
from bot.services.location_service import LOCATION_SERVICE
from bot.services.player_service import title_for_player
from bot.utils.embeds import WARM_GOLD, embed
from bot.utils.time import human_duration


def build_profile_embed(
    *,
    display_name: str,
    player: Player,
    energy_state: EnergyState,
    stats: CombatStats,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
) -> discord.Embed:
    response = embed(display_name, f"{title_for_player(player)}\n⚔️ Combat ⚔️", colour=WARM_GOLD)
    response.add_field(name="Level", value=str(player.combat_level))
    response.add_field(name="HP", value=f"{player.current_hp}/{stats.max_hp}")
    response.add_field(name="Gold", value=str(player.gold))

    response.add_field(name="ATK", value=str(stats.attack))
    response.add_field(name="DEF", value=str(stats.defense))
    response.add_field(name="SPD", value=str(stats.speed))
    response.add_field(name="XP", value=f"{player.combat_xp}/{player.combat_xp_to_next_level}")
    response.add_field(name="Unspent Stat Points", value=str(player.unspent_stat_points))

    _add_header(response, "🧭 Explore 🧭")
    response.add_field(name="Energy", value=f"{energy_state.energy}/{MAX_ENERGY}")
    response.add_field(name="Next Energy", value=human_duration(energy_state.seconds_until_next))
    response.add_field(name="Explorations", value=str(player.total_explorations))
    response.add_field(name="Successful", value=str(player.successful_explorations))
    response.add_field(name="Discoveries", value=str(player.discoveries_found))
    response.add_field(name="Hero / Villain Influence", value=f"{player.hero_influence} : {player.villain_influence}")
    response.add_field(name="Defending", value=_defending_value(player), inline=False)
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("user_profile"))
    return response


def _add_header(response: discord.Embed, name: str) -> None:
    response.add_field(name="\u200b", value=f"**{name}**", inline=False)


def _defending_value(player: Player) -> str:
    if player.is_defending and player.defense_selected_dungeon_level:
        return f"Dungeon Level {player.defense_selected_dungeon_level}"
    return "Not defending"
