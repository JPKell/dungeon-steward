from __future__ import annotations

import logging

import discord
from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

from bot import __version__
from bot.config import ENERGY_REGEN_SECONDS, MAX_ENERGY
from bot.models import Player
from bot.services.encounter_service import Encounter
from bot.services.energy_service import InsufficientEnergyError
from bot.services.exploration_service import (
    ExplorationAlreadyResolvedError,
    ExplorationExpiredError,
    ExplorationNotOwnedError,
    ExplorationService,
)
from bot.services.player_service import title_for_player
from bot.utils.embeds import DEEP_NAVY, MIDNIGHT_BLUE, WARM_GOLD, embed
from bot.utils.time import discord_relative_timestamp, human_duration

log = logging.getLogger(__name__)


class ExplorationView(discord.ui.View):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        resolution_key: str,
        owner_user_id: int,
        encounter: Encounter,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.exploration_service = exploration_service
        self.resolution_key = resolution_key
        self.owner_user_id = owner_user_id
        for choice in encounter.choices:
            self.add_item(ExplorationButton(choice.key, choice.label))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "This expedition belongs to another player.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def resolve_choice(self, interaction: discord.Interaction, choice_key: str) -> None:
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                result = self.exploration_service.resolve(
                    db,
                    resolution_key=self.resolution_key,
                    choice_key=choice_key,
                    acting_user_id=interaction.user.id,
                )
                db.commit()
        except ExplorationNotOwnedError:
            await interaction.followup.send("This expedition belongs to another player.", ephemeral=True)
            return
        except ExplorationExpiredError:
            await interaction.followup.send("That expedition has expired.", ephemeral=True)
            return
        except ExplorationAlreadyResolvedError:
            await interaction.followup.send("That expedition has already been resolved.", ephemeral=True)
            return
        except Exception:
            log.exception("Failed to resolve exploration")
            await interaction.followup.send(
                "The dungeon coughed up the magic blue smoke. "
                "Something is wrong with the dungeon. Please try again.",
                ephemeral=True,
            )
            return

        self.stop()
        result_embed = embed(result.encounter.title, result.choice.result_text, colour=WARM_GOLD)
        result_embed.add_field(name="Rewards", value=f"{result.gold} gold\n{result.experience} XP")
        result_embed.add_field(name="Energy", value=f"{result.energy_state.energy}/12 remaining")
        if result.discovery_name:
            label = "New Discovery" if result.new_discovery else "Discovery Revisited"
            result_embed.add_field(name=label, value=result.discovery_name, inline=False)
        if result.leveled_up:
            result_embed.add_field(name="Level Up", value="Your dungeon title grows heavier.", inline=False)
        if result.energy_state.next_energy_at:
            result_embed.add_field(
                name="Next Energy",
                value=human_duration(result.energy_state.seconds_until_next),
            )
        await interaction.edit_original_response(
            embed=result_embed,
            view=PostExplorationView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                owner_user_id=self.owner_user_id,
            ),
        )


class ExplorationButton(discord.ui.Button):
    def __init__(self, choice_key: str, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"explore:{choice_key}")
        self.choice_key = choice_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ExplorationView):
            await interaction.response.send_message("This expedition is no longer available.", ephemeral=True)
            return
        await view.resolve_choice(interaction, self.choice_key)


def build_hall_embed() -> discord.Embed:
    hall = embed(
        "Steward's Hall",
        "The planning table is covered in maps, candle stubs, and exactly one mug labelled "
        "'do not polymorph.' Choose what to do next.",
        colour=DEEP_NAVY,
    )
    hall.add_field(
        name="Available Actions",
        value=(
            "Explore the dungeon\n"
            "Check your profile\n"
            "Review energy\n"
            "Inspect the shared dungeon\n"
            "View the leaderboard\n"
            "Read help"
        ),
        inline=False,
    )
    return hall


class DungeonActionView(discord.ui.View):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        owner_user_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.exploration_service = exploration_service
        self.owner_user_id = owner_user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "These dungeon controls belong to another player.",
                ephemeral=True,
            )
            return False
        return True

    async def start_exploration(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Dungeon expeditions only work in a server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                self.exploration_service.discoveries.sync_content(db)
                started = self.exploration_service.start(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                db.commit()
        except InsufficientEnergyError:
            with self.session_factory() as db:
                player = self.exploration_service.players.get_or_create(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                state = self.exploration_service.energy.recalculate(player)
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
            log.exception("Explore button failed")
            await interaction.followup.send(
                "The dungeon door jammed. Please try again.",
                ephemeral=True,
            )
            return

        self.stop()
        encounter_embed = embed(
            started.encounter.title,
            started.encounter.description,
            colour=DEEP_NAVY,
        )
        encounter_embed.add_field(name="Cost", value="Entering the dungeon consumes 1 energy.")
        encounter_embed.add_field(
            name="Remaining Energy",
            value=f"{started.energy_state.energy}/{MAX_ENERGY}",
        )
        await interaction.edit_original_response(
            embed=encounter_embed,
            view=ExplorationView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                resolution_key=started.session.resolution_key,
                owner_user_id=interaction.user.id,
                encounter=started.encounter,
            ),
        )

    def compact_view(self) -> PostExplorationView:
        return PostExplorationView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            owner_user_id=self.owner_user_id,
        )


class PostExplorationView(DungeonActionView):
    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Steward's Hall", style=discord.ButtonStyle.secondary)
    async def hall(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            embed=build_hall_embed(),
            view=StewardsHallView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                owner_user_id=self.owner_user_id,
            ),
        )


class StewardsHallView(DungeonActionView):
    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary, row=0)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Profile", style=discord.ButtonStyle.secondary, row=0)
    async def profile(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Profiles are server-specific.",
                ephemeral=True,
            )
            return
        with self.session_factory() as db:
            player = self.exploration_service.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            state = self.exploration_service.energy.recalculate(player)
            db.commit()
            profile_embed = embed(interaction.user.display_name, title_for_player(player), colour=WARM_GOLD)
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
        await interaction.response.edit_message(embed=profile_embed, view=self.compact_view())

    @discord.ui.button(label="Energy", style=discord.ButtonStyle.secondary, row=0)
    async def energy(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Energy is server-specific.",
                ephemeral=True,
            )
            return
        with self.session_factory() as db:
            player = self.exploration_service.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            state = self.exploration_service.energy.recalculate(player)
            db.commit()
        response = embed("Dungeon Energy", colour=MIDNIGHT_BLUE)
        response.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
        response.add_field(name="Regeneration", value="1 energy every 2 hours")
        response.add_field(name="Explorations Available", value=str(state.energy))
        response.add_field(name="Next Energy", value=discord_relative_timestamp(state.next_energy_at))
        response.add_field(name="Full Energy", value=discord_relative_timestamp(state.full_energy_at))
        response.set_footer(text=f"Energy cap: {MAX_ENERGY} | Regen: {ENERGY_REGEN_SECONDS // 3600} hours")
        await interaction.response.edit_message(embed=response, view=self.compact_view())

    @discord.ui.button(label="Dungeon", style=discord.ButtonStyle.secondary, row=1)
    async def dungeon(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Dungeon status is server-specific.",
                ephemeral=True,
            )
            return
        with self.session_factory() as db:
            dungeon = self.exploration_service.players.get_or_create_guild(
                db,
                guild_id=interaction.guild_id,
            )
            objective = self.exploration_service.weekly.get_active(
                db,
                guild_id=interaction.guild_id,
            )
            db.commit()
            status_embed = embed(
                dungeon.name,
                "The shared dungeon prefers balance over conquest.",
                colour=DEEP_NAVY,
            )
            status_embed.add_field(name="Level", value=str(dungeon.level))
            status_embed.add_field(name="Gold", value=str(dungeon.gold))
            status_embed.add_field(name="Hero Influence", value=str(dungeon.hero_influence))
            status_embed.add_field(name="Villain Influence", value=str(dungeon.villain_influence))
            status_embed.add_field(name="Stability", value=f"{dungeon.stability}/100")
            status_embed.add_field(name="Weekly Objective", value=objective.title, inline=False)
            status_embed.add_field(
                name="Progress",
                value=(
                    f"{objective.progress_value}/{objective.target_value} | "
                    f"Ends {discord_relative_timestamp(objective.ends_at)}"
                ),
                inline=False,
            )
        await interaction.response.edit_message(embed=status_embed, view=self.compact_view())

    @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.secondary, row=1)
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Leaderboards are server-specific.",
                ephemeral=True,
            )
            return
        with self.session_factory() as db:
            rows = db.execute(
                select(Player.display_name, Player.experience)
                .where(Player.guild_id == interaction.guild_id, Player.is_active.is_(True))
                .order_by(desc(Player.experience))
                .limit(10)
            ).all()
        board = embed("Dungeon Leaderboard", colour=WARM_GOLD)
        if rows:
            board.description = "\n".join(
                f"{index}. {name}: {value} XP" for index, (name, value) in enumerate(rows, start=1)
            )
        else:
            board.description = "No entries yet. The dungeon awaits its first questionable decision."
        await interaction.response.edit_message(embed=board, view=self.compact_view())

    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, row=1)
    async def help(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
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
        await interaction.response.edit_message(embed=help_embed, view=self.compact_view())
