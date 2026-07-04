from __future__ import annotations

import logging

import discord
from discord import app_commands
from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

from bot import __version__
from bot.config import MAX_ENERGY
from bot.models import Player, WeeklyPlayerContribution
from bot.services.defense_service import (
    AlreadyDefendingError,
    DefenseService,
    InvalidDungeonLevelError,
    NotDefendingError,
)
from bot.services.discovery_service import DiscoveryService
from bot.services.energy_service import EnergyService, InsufficientEnergyError
from bot.services.equipment_service import get_effective_combat_stats
from bot.services.exploration_service import ExplorationService
from bot.services.player_service import PlayerService, title_for_player
from bot.services.progression_service import (
    ALLOCATABLE_STATS,
    allocate_stat_points,
    get_explore_cooldown_minutes,
    get_max_defense_minutes,
    sync_combat_progression,
)
from bot.services.shop_service import (
    InsufficientGoldError,
    InvalidShopSelectionError,
    ShopService,
)
from bot.services.weekly_objective_service import WeeklyObjectiveService
from bot.utils.defense_embeds import build_defense_report_embed, build_defense_started_embed
from bot.utils.embeds import DEEP_NAVY, MIDNIGHT_BLUE, WARM_GOLD, embed
from bot.utils.shop_embeds import build_purchase_embed, build_shop_embed
from bot.utils.time import discord_relative_timestamp, human_duration
from bot.views.exploration import (
    ExplorationView,
    PostExplorationView,
    ShopView,
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
        self.defense = DefenseService(players=self.players)
        self.shop = ShopService(players=self.players)
        self.discoveries = DiscoveryService()
        self.weekly = WeeklyObjectiveService()

    def _action_view(self, user_id: int) -> PostExplorationView:
        return PostExplorationView(
            session_factory=self.session_factory,
            exploration_service=self.exploration,
            defense_service=self.defense,
            shop_service=self.shop,
            owner_user_id=user_id,
        )

    def _hall_view(self, user_id: int) -> StewardsHallView:
        return StewardsHallView(
            session_factory=self.session_factory,
            exploration_service=self.exploration,
            defense_service=self.defense,
            shop_service=self.shop,
            owner_user_id=user_id,
        )

    async def _resolve_defense_before_explore(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return True
        try:
            with self.session_factory() as db:
                report = self.defense.resolve_before_explore(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                db.commit()
        except Exception:
            log.exception("Failed to resolve defense before exploration")
            await interaction.followup.send(
                "The defense ledger would not close cleanly. Please try again.",
                ephemeral=True,
            )
            return False
        if report is not None:
            await interaction.followup.send(embed=build_defense_report_embed(report))
        return True

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
        if not await self._resolve_defense_before_explore(interaction):
            return
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
                cooldown_seconds = get_explore_cooldown_minutes(player.explore_level) * 60
                db.commit()
            await interaction.followup.send(
                "You do not currently have enough energy to explore.\n\n"
                f"Energy: {state.energy}/{MAX_ENERGY}\n"
                f"Next energy: {human_duration(state.seconds_until_next)}\n"
                f"Energy regenerates every {human_duration(cooldown_seconds)} and can accumulate for up to 24 hours.",
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
                defense_service=self.defense,
                shop_service=self.shop,
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
        await interaction.response.defer()
        target = member or interaction.user
        report = None
        with self.session_factory() as db:
            player = self.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=target.id,
                display_name=target.display_name,
            )
            if target.id == interaction.user.id:
                report = self.defense.resolve_if_expired(db, player)
            state = self.energy.recalculate(player)
            profile_embed = embed(target.display_name, title_for_player(player), colour=WARM_GOLD)
            sync_combat_progression(player)
            stats = get_effective_combat_stats(player)
            db.commit()
            profile_embed.add_field(name="Explore Level", value=str(player.explore_level))
            profile_embed.add_field(name="Explore XP", value=str(player.experience))
            profile_embed.add_field(
                name="Explore Cooldown",
                value=human_duration(get_explore_cooldown_minutes(player.explore_level) * 60),
            )
            profile_embed.add_field(name="Combat Level", value=str(player.combat_level))
            profile_embed.add_field(
                name="Combat XP",
                value=f"{player.combat_xp}/{player.combat_xp_to_next_level}",
            )
            profile_embed.add_field(name="HP", value=f"{player.current_hp}/{stats.max_hp}")
            profile_embed.add_field(
                name="Combat Stats",
                value=f"Attack {stats.attack}\nDefense {stats.defense}\nSpeed {stats.speed}",
            )
            profile_embed.add_field(name="Unspent Stat Points", value=str(player.unspent_stat_points))
            profile_embed.add_field(name="Gold", value=str(player.gold))
            profile_embed.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
            profile_embed.add_field(name="Next Energy", value=human_duration(state.seconds_until_next))
            profile_embed.add_field(name="Explorations", value=str(player.total_explorations))
            profile_embed.add_field(name="Successful", value=str(player.successful_explorations))
            profile_embed.add_field(name="Discoveries", value=str(player.discoveries_found))
            profile_embed.add_field(name="Hero Influence", value=str(player.hero_influence))
            profile_embed.add_field(name="Villain Influence", value=str(player.villain_influence))
            if player.is_defending and player.defense_selected_dungeon_level:
                profile_embed.add_field(
                    name="Defending",
                    value=f"Dungeon Level {player.defense_selected_dungeon_level}",
                    inline=False,
                )
        if report is not None:
            await interaction.followup.send(embed=build_defense_report_embed(report))
        await interaction.followup.send(
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
            cooldown_seconds = get_explore_cooldown_minutes(player.explore_level) * 60
            db.commit()
        response = embed("Dungeon Energy", colour=MIDNIGHT_BLUE)
        response.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
        response.add_field(name="Regeneration", value=f"1 energy every {human_duration(cooldown_seconds)}")
        response.add_field(name="Explorations Available", value=str(state.energy))
        response.add_field(name="Next Energy", value=discord_relative_timestamp(state.next_energy_at))
        response.add_field(name="Full Energy", value=discord_relative_timestamp(state.full_energy_at))
        response.set_footer(text=f"Energy cap: {MAX_ENERGY} | Explore Level: {player.explore_level}")
        await interaction.response.send_message(
            embed=response,
            view=self._action_view(interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="defend", description="Defend a dungeon level from one-minute attacks")
    @app_commands.describe(dungeon_level="Dungeon difficulty from 1 through 20")
    async def defend(
        self,
        interaction: discord.Interaction,
        dungeon_level: app_commands.Range[int, 1, 20],
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Defending only works in a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                started = self.defense.start(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                    dungeon_level=int(dungeon_level),
                    channel_id=interaction.channel_id,
                )
                db.commit()
        except AlreadyDefendingError:
            await interaction.followup.send("You are already defending. Use `/dungeon stop-defending` first.", ephemeral=True)
            return
        except InvalidDungeonLevelError:
            await interaction.followup.send("Choose a dungeon level from 1 through 20.", ephemeral=True)
            return
        except Exception:
            log.exception("Defend command failed")
            await interaction.followup.send("The guard roster fell off the wall. Please try again.", ephemeral=True)
            return
        await interaction.followup.send(
            embed=build_defense_started_embed(started),
            view=self._action_view(interaction.user.id),
        )

    @app_commands.command(name="stop-defending", description="Stop defending and collect the defense report")
    async def stop_defending(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Defending only works in a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                report = self.defense.stop(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                )
                db.commit()
        except NotDefendingError:
            await interaction.followup.send("You are not currently defending.", ephemeral=True)
            return
        except Exception:
            log.exception("Stop defending command failed")
            await interaction.followup.send("The defense ledger would not close. Please try again.", ephemeral=True)
            return
        await interaction.followup.send(
            embed=build_defense_report_embed(report),
            view=self._action_view(interaction.user.id),
        )

    @app_commands.command(name="shop", description="View this hour's equipment shop")
    async def shop_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("The shop is server-specific.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = self.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            stock = self.shop.stock_for_player(player)
            db.commit()
            shop_embed = build_shop_embed(stock, player=player, equipment=self.shop.equipment)
        await interaction.response.send_message(
            embed=shop_embed,
            view=ShopView(
                session_factory=self.session_factory,
                exploration_service=self.exploration,
                defense_service=self.defense,
                shop_service=self.shop,
                owner_user_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="buy", description="Buy and equip an item from this hour's shop")
    @app_commands.describe(item_number="Shop item number from 1 through 10")
    async def buy(self, interaction: discord.Interaction, item_number: app_commands.Range[int, 1, 10]) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("The shop is server-specific.", ephemeral=True)
            return
        try:
            with self.session_factory() as db:
                purchase = self.shop.purchase(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                    stock_number=int(item_number),
                )
                db.commit()
        except InvalidShopSelectionError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        except InsufficientGoldError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        except Exception:
            log.exception("Buy command failed")
            await interaction.response.send_message("The shop ledger jammed. Please try again.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=build_purchase_embed(purchase),
            view=self._action_view(interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="stats", description="View combat stats or spend stat points")
    @app_commands.describe(stat="Stat to improve", amount="Number of points to spend")
    @app_commands.choices(
        stat=[
            app_commands.Choice(name="Attack", value="attack"),
            app_commands.Choice(name="Defense", value="defense"),
            app_commands.Choice(name="Speed", value="speed"),
        ]
    )
    async def stats(
        self,
        interaction: discord.Interaction,
        stat: app_commands.Choice[str] | None = None,
        amount: int = 0,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Stats are server-specific.", ephemeral=True)
            return
        selected_stat = stat.value if stat else None
        if selected_stat is not None and selected_stat not in ALLOCATABLE_STATS:
            await interaction.response.send_message("Choose attack, defense, or speed.", ephemeral=True)
            return
        if selected_stat is not None and amount <= 0:
            await interaction.response.send_message("Amount must be a positive integer.", ephemeral=True)
            return

        try:
            with self.session_factory() as db:
                player = db.scalar(
                    select(Player)
                    .where(
                        Player.guild_id == interaction.guild_id,
                        Player.discord_user_id == interaction.user.id,
                    )
                    .with_for_update()
                )
                if player is None:
                    player = self.players.get_or_create(
                        db,
                        guild_id=interaction.guild_id,
                        user_id=interaction.user.id,
                        display_name=interaction.user.display_name,
                    )
                if selected_stat is not None:
                    allocate_stat_points(player, selected_stat, amount)
                sync_combat_progression(player)
                stats = get_effective_combat_stats(player)
                db.commit()
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        except Exception:
            log.exception("Stats command failed")
            await interaction.response.send_message("The stat ledger jammed. Please try again.", ephemeral=True)
            return

        stats_embed = embed("Combat Stats", colour=WARM_GOLD)
        stats_embed.add_field(name="Combat Level", value=str(player.combat_level))
        stats_embed.add_field(name="Combat XP", value=f"{player.combat_xp}/{player.combat_xp_to_next_level}")
        stats_embed.add_field(name="HP", value=f"{player.current_hp}/{stats.max_hp}")
        stats_embed.add_field(
            name="Stats",
            value=f"Attack {stats.attack}\nDefense {stats.defense}\nSpeed {stats.speed}",
        )
        stats_embed.add_field(name="Unspent Points", value=str(player.unspent_stat_points))
        stats_embed.add_field(
            name="Defense Duration",
            value=human_duration(get_max_defense_minutes(player.combat_level) * 60),
        )
        if selected_stat is not None:
            stats_embed.description = f"Added {amount} point(s) to {selected_stat}."
        await interaction.response.send_message(
            embed=stats_embed,
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
            "discoveries, and influence. Explore Level shortens energy recovery down to 30 minutes. "
            "Defending resolves one attack per completed minute and awards Combat XP and gold. "
            "The equipment shop refreshes hourly by Combat Level. "
            "Weekly objectives give the whole server a reason to keep returning."
        )
        help_embed.add_field(
            name="Commands",
            value=(
                "/dungeon explore\n/dungeon defend\n/dungeon stop-defending\n"
                "/dungeon shop\n/dungeon buy\n/dungeon stats\n/dungeon profile\n"
                "/dungeon energy\n/dungeon status\n/dungeon leaderboard"
            ),
            inline=False,
        )
        help_embed.add_field(name="Version", value=__version__)
        await interaction.response.send_message(
            embed=help_embed,
            view=self._action_view(interaction.user.id),
            ephemeral=True,
        )
