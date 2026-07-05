from __future__ import annotations

import logging
from collections.abc import Callable

import discord
from discord import app_commands
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from bot.commands.permissions import is_staff
from bot.config import MAX_ENERGY, Settings
from bot.models import (
    EncounterHistory,
    ExplorationSession,
    Player,
    PlayerDiscovery,
    WeeklyPlayerContribution,
)
from bot.services.content_runtime import refresh_runtime_content_from_database
from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService
from bot.services.energy_service import EnergyService
from bot.services.player_service import PlayerService
from bot.utils.embeds import embed

log = logging.getLogger(__name__)


class DungeonAdminGroup(app_commands.Group):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        settings: Settings,
        content_reload_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(name="dungeon-admin", description="Staff controls for Dungeon Steward")
        self.session_factory = session_factory
        self.settings = settings
        self.content_reload_callback = content_reload_callback
        self.energy = EnergyService()
        self.players = PlayerService()
        self.discoveries = DiscoveryService()
        self.encounters = EncounterService()

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if is_staff(interaction, self.settings.discord_staff_role_id):
            return True
        await interaction.response.send_message("You do not have access to dungeon staff controls.", ephemeral=True)
        return False

    @app_commands.command(name="announce", description="Post a dungeon announcement")
    async def announce(self, interaction: discord.Interaction, message: str) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(embed=embed("Dungeon Notice", message))
        log.info("Dungeon announcement sent by user_id=%s", interaction.user.id)

    @app_commands.command(name="grant-energy", description="Grant energy to a player")
    async def grant_energy(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not await self._guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = self.players.get_or_create(
                db, guild_id=interaction.guild_id, user_id=member.id, display_name=member.display_name
            )
            state = self.energy.grant(player, amount)
            db.commit()
        await interaction.response.send_message(
            f"Granted energy. {member.display_name} now has {state.energy}/{MAX_ENERGY}.", ephemeral=True
        )

    @app_commands.command(name="set-energy", description="Set a player's energy")
    async def set_energy(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not await self._guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = self.players.get_or_create(
                db, guild_id=interaction.guild_id, user_id=member.id, display_name=member.display_name
            )
            state = self.energy.set_energy(player, amount)
            db.commit()
        await interaction.response.send_message(
            f"Set energy. {member.display_name} now has {state.energy}/{MAX_ENERGY}.", ephemeral=True
        )

    @app_commands.command(name="reset-player", description="Reset a player's dungeon progress")
    async def reset_player(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not await self._guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = db.scalar(
                select(Player).where(Player.guild_id == interaction.guild_id, Player.discord_user_id == member.id)
            )
            if player:
                db.execute(delete(PlayerDiscovery).where(PlayerDiscovery.player_id == player.id))
                db.execute(
                    delete(WeeklyPlayerContribution).where(
                        WeeklyPlayerContribution.player_id == player.id
                    )
                )
                db.execute(delete(EncounterHistory).where(EncounterHistory.player_id == player.id))
                db.execute(delete(ExplorationSession).where(ExplorationSession.player_id == player.id))
                db.delete(player)
            db.commit()
        await interaction.response.send_message(f"Reset {member.display_name}'s dungeon profile.", ephemeral=True)

    @app_commands.command(name="event-status", description="Validate content and show counts")
    async def event_status(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        discoveries = self.discoveries.load_content()
        await interaction.response.send_message(
            f"Encounters: {len(self.encounters.encounters)}\nDiscoveries: {len(discoveries)}",
            ephemeral=True,
        )

    @app_commands.command(name="reload-content", description="Reload game content from the database")
    async def reload_content(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        refresh_runtime_content_from_database(self.session_factory)
        self.discoveries = DiscoveryService()
        self.encounters = EncounterService()
        if self.content_reload_callback is not None:
            self.content_reload_callback()
        await interaction.response.send_message("Database content reloaded.", ephemeral=True)
