from __future__ import annotations

import logging

import discord
from discord import app_commands
from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

from bot import __version__
from bot.config import ENERGY_REGEN_SECONDS, MAX_ENERGY
from bot.models import Player, WeeklyPlayerContribution
from bot.services.discovery_service import DiscoveryService
from bot.services.energy_service import EnergyService, InsufficientEnergyError
from bot.services.exploration_service import ExplorationService
from bot.services.player_service import PlayerService, title_for_player
from bot.services.weekly_objective_service import WeeklyObjectiveService
from bot.utils.embeds import DEEP_NAVY, MIDNIGHT_BLUE, WARM_GOLD, embed
from bot.utils.time import discord_relative_timestamp, human_duration
from bot.views.exploration import (
    ExplorationView,
    PostExplorationView,
    StewardsHallView,
    build_hall_embed,
)

log = logging.getLogger(__name__)


class DungeonGroup(app_commands.Group):
    def __init__(self, *, session_factory: sessionmaker) -> None:
        super().__init__(name="dungeon", description="Explore the Kellrond community dungeon")
        self.session_factory = session_factory
        self.energy = EnergyService()
        self.players = PlayerService()
        self.exploration = ExplorationService()
        self.discoveries = DiscoveryService()
        self.weekly = WeeklyObjectiveService()

    def _action_view(self, user_id: int) -> PostExplorationView:
        return PostExplorationView(
            session_factory=self.session_factory,
            exploration_service=self.exploration,
            owner_user_id=user_id,
        )

    def _hall_view(self, user_id: int) -> StewardsHallView:
        return StewardsHallView(
            session_factory=self.session_factory,
            exploration_service=self.exploration,
            owner_user_id=user_id,
        )

    @app_commands.command(name="hall", description="Visit the Steward's Hall to choose your next dungeon action")
    async def hall(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_hall_embed(),
            view=self._hall_view(interaction.user.id),
        )

    @app_commands.command(name="explore", description="Spend one energy to explore the dungeon")
    async def explore(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Dungeon expeditions only work in a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                self.discoveries.sync_content(db)
                started = self.exploration.start(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                db.commit()
        except InsufficientEnergyError:
            with self.session_factory() as db:
                player = self.players.get_or_create(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                state = self.energy.recalculate(player)
                db.commit()
            await interaction.followup.send(
                "You do not currently have enough energy to explore.\n\n"
                f"Energy: {state.energy}/{MAX_ENERGY}\n"
                f"Next energy: {human_duration(state.seconds_until_next)}\n"
                "Energy regenerates every 2 hours and can accumulate for up to 24 hours.",
                ephemeral=True,
            )
            return
        except Exception:
            log.exception("Explore command failed")
            await interaction.followup.send("The dungeon door jammed. Please try again.", ephemeral=True)
            return

        encounter_embed = embed(started.encounter.title, started.encounter.description, colour=DEEP_NAVY)
        encounter_embed.add_field(name="Cost", value="Entering the dungeon consumes 1 energy.")
        encounter_embed.add_field(name="Remaining Energy", value=f"{started.energy_state.energy}/{MAX_ENERGY}")
        await interaction.followup.send(
            embed=encounter_embed,
            view=ExplorationView(
                session_factory=self.session_factory,
                exploration_service=self.exploration,
                resolution_key=started.session.resolution_key,
                owner_user_id=interaction.user.id,
                encounter=started.encounter,
            ),
        )

    @app_commands.command(name="profile", description="View your dungeon profile")
    @app_commands.describe(member="Optional member to inspect")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Profiles are server-specific.", ephemeral=True)
            return
        target = member or interaction.user
        with self.session_factory() as db:
            player = self.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=target.id,
                display_name=target.display_name,
            )
            state = self.energy.recalculate(player)
            db.commit()
            profile_embed = embed(target.display_name, title_for_player(player), colour=WARM_GOLD)
            profile_embed.add_field(name="Level", value=str(player.level))
            profile_embed.add_field(name="Experience", value=str(player.experience))
            profile_embed.add_field(name="Gold", value=str(player.gold))
            profile_embed.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
            profile_embed.add_field(name="Next Energy", value=human_duration(state.seconds_until_next))
            profile_embed.add_field(name="Explorations", value=str(player.total_explorations))
            profile_embed.add_field(name="Successful", value=str(player.successful_explorations))
            profile_embed.add_field(name="Discoveries", value=str(player.discoveries_found))
            profile_embed.add_field(name="Hero Influence", value=str(player.hero_influence))
            profile_embed.add_field(name="Villain Influence", value=str(player.villain_influence))
        await interaction.response.send_message(
            embed=profile_embed,
            view=self._action_view(interaction.user.id),
        )

    @app_commands.command(name="energy", description="Check your dungeon energy")
    async def energy_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Energy is server-specific.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = self.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            state = self.energy.recalculate(player)
            db.commit()
        response = embed("Dungeon Energy", colour=MIDNIGHT_BLUE)
        response.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
        response.add_field(name="Regeneration", value="1 energy every 2 hours")
        response.add_field(name="Explorations Available", value=str(state.energy))
        response.add_field(name="Next Energy", value=discord_relative_timestamp(state.next_energy_at))
        response.add_field(name="Full Energy", value=discord_relative_timestamp(state.full_energy_at))
        response.set_footer(text=f"Energy cap: {MAX_ENERGY} | Regen: {ENERGY_REGEN_SECONDS // 3600} hours")
        await interaction.response.send_message(
            embed=response,
            view=self._action_view(interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="status", description="View the shared server dungeon")
    async def status(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Dungeon status is server-specific.", ephemeral=True)
            return
        with self.session_factory() as db:
            dungeon = self.players.get_or_create_guild(db, guild_id=interaction.guild_id)
            objective = self.weekly.get_active(db, guild_id=interaction.guild_id)
            db.commit()
            status_embed = embed(dungeon.name, "The shared dungeon prefers balance over conquest.", colour=DEEP_NAVY)
            status_embed.add_field(name="Level", value=str(dungeon.level))
            status_embed.add_field(name="Gold", value=str(dungeon.gold))
            status_embed.add_field(name="Hero Influence", value=str(dungeon.hero_influence))
            status_embed.add_field(name="Villain Influence", value=str(dungeon.villain_influence))
            status_embed.add_field(name="Stability", value=f"{dungeon.stability}/100")
            status_embed.add_field(name="Weekly Objective", value=objective.title, inline=False)
            status_embed.add_field(
                name="Progress",
                value=f"{objective.progress_value}/{objective.target_value} | Ends {discord_relative_timestamp(objective.ends_at)}",
                inline=False,
            )
        await interaction.response.send_message(
            embed=status_embed,
            view=self._action_view(interaction.user.id),
        )

    @app_commands.command(name="leaderboard", description="Show the server leaderboard")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Experience", value="experience"),
            app_commands.Choice(name="Gold", value="gold"),
            app_commands.Choice(name="Explorations", value="total_explorations"),
            app_commands.Choice(name="Discoveries", value="discoveries_found"),
            app_commands.Choice(name="Weekly Contribution", value="weekly"),
        ]
    )
    async def leaderboard(
        self, interaction: discord.Interaction, category: app_commands.Choice[str] | None = None
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Leaderboards are server-specific.", ephemeral=True)
            return
        selected = category.value if category else "experience"
        with self.session_factory() as db:
            if selected == "weekly":
                objective = self.weekly.get_active(db, guild_id=interaction.guild_id)
                rows = db.execute(
                    select(Player.display_name, WeeklyPlayerContribution.contribution_value)
                    .join(WeeklyPlayerContribution, WeeklyPlayerContribution.player_id == Player.id)
                    .where(WeeklyPlayerContribution.weekly_objective_id == objective.id)
                    .order_by(desc(WeeklyPlayerContribution.contribution_value))
                    .limit(10)
                ).all()
            else:
                column = getattr(Player, selected)
                rows = db.execute(
                    select(Player.display_name, column)
                    .where(Player.guild_id == interaction.guild_id, Player.is_active.is_(True))
                    .order_by(desc(column))
                    .limit(10)
                ).all()
        board = embed("Dungeon Leaderboard", colour=WARM_GOLD)
        if rows:
            board.description = "\n".join(
                f"{index}. {name}: {value}" for index, (name, value) in enumerate(rows, start=1)
            )
        else:
            board.description = "No entries yet. The dungeon awaits its first questionable decision."
        await interaction.response.send_message(
            embed=board,
            view=self._action_view(interaction.user.id),
        )

    @app_commands.command(name="help", description="Learn how the dungeon works")
    async def help_command(self, interaction: discord.Interaction) -> None:
        help_embed = embed("Dungeon Help", colour=DEEP_NAVY)
        help_embed.description = (
            "Spend 1 energy with `/dungeon explore`, choose a response, and earn gold, XP, "
            "discoveries, and influence. Energy regenerates every 2 hours up to 12. "
            "Choices can help heroes, empower villains, or steady the shared dungeon. "
            "Weekly objectives give the whole server a reason to keep returning."
        )
        help_embed.add_field(
            name="Commands",
            value="/dungeon explore\n/dungeon hall\n/dungeon profile\n/dungeon energy\n/dungeon status\n/dungeon leaderboard",
            inline=False,
        )
        help_embed.add_field(name="Version", value=__version__)
        await interaction.response.send_message(
            embed=help_embed,
            view=self._action_view(interaction.user.id),
            ephemeral=True,
        )
