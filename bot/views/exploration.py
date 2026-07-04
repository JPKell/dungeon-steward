from __future__ import annotations

import logging

import discord
from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

from bot import __version__
from bot.config import MAX_ENERGY
from bot.models import Player
from bot.services.defense_service import (
    AlreadyDefendingError,
    DefenseService,
    InvalidDungeonLevelError,
    NotDefendingError,
)
from bot.services.encounter_service import Encounter
from bot.services.energy_service import InsufficientEnergyError
from bot.services.equipment_service import get_effective_combat_stats
from bot.services.exploration_service import (
    ExplorationAlreadyResolvedError,
    ExplorationExpiredError,
    ExplorationNotOwnedError,
    ExplorationService,
)
from bot.services.player_service import title_for_player
from bot.services.progression_service import get_explore_cooldown_minutes, sync_combat_progression
from bot.services.shop_service import (
    InsufficientGoldError,
    InvalidShopSelectionError,
    ShopService,
)
from bot.utils.defense_embeds import build_defense_report_embed, build_defense_started_embed
from bot.utils.embeds import DEEP_NAVY, MIDNIGHT_BLUE, WARM_GOLD, embed
from bot.utils.shop_embeds import build_purchase_embed, build_shop_embed
from bot.utils.time import discord_relative_timestamp, human_duration

log = logging.getLogger(__name__)


class ExplorationView(discord.ui.View):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        resolution_key: str,
        owner_user_id: int,
        encounter: Encounter,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.exploration_service = exploration_service
        self.defense_service = defense_service
        self.shop_service = shop_service
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
            result_embed.add_field(name="Explore Level Up", value="Your dungeon title grows heavier.", inline=False)
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
                defense_service=self.defense_service,
                shop_service=self.shop_service,
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
            "Defend a dungeon level\n"
            "Visit the equipment shop\n"
            "Check your profile\n"
            "Review combat stats\n"
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
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.exploration_service = exploration_service
        self.defense_service = defense_service
        self.shop_service = shop_service
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
        if not await self.resolve_defense_before_explore(interaction):
            return
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
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                resolution_key=started.session.resolution_key,
                owner_user_id=interaction.user.id,
                encounter=started.encounter,
            ),
        )

    async def resolve_defense_before_explore(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return True
        try:
            with self.session_factory() as db:
                report = self.defense_service.resolve_before_explore(
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

    async def show_defense_selector(self, interaction: discord.Interaction) -> None:
        selector = embed(
            "Choose Defense Level",
            "Select a dungeon level from 1 through 20. Higher levels pay better and hit harder.",
            colour=DEEP_NAVY,
        )
        await interaction.response.edit_message(
            embed=selector,
            view=DefenseLevelSelectView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
            ),
        )

    async def stop_defending(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Defending only works in a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                report = self.defense_service.stop(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                )
                db.commit()
        except NotDefendingError:
            await interaction.followup.send("You are not currently defending.", ephemeral=True)
            return
        except Exception:
            log.exception("Stop defending button failed")
            await interaction.followup.send("The defense ledger would not close. Please try again.", ephemeral=True)
            return
        await interaction.followup.send(embed=build_defense_report_embed(report))
        await interaction.edit_original_response(view=self.compact_view())

    async def show_shop(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("The shop is server-specific.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = self.exploration_service.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            stock = self.shop_service.stock_for_player(player)
            db.commit()
            shop_embed = build_shop_embed(stock, player=player, equipment=self.shop_service.equipment)
        await interaction.response.edit_message(
            embed=shop_embed,
            view=ShopView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
            ),
        )

    async def buy_shop_item(self, interaction: discord.Interaction, stock_number: int) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("The shop is server-specific.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                purchase = self.shop_service.purchase(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                    stock_number=stock_number,
                )
                db.commit()
        except InvalidShopSelectionError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except InsufficientGoldError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            log.exception("Shop purchase button failed")
            await interaction.followup.send("The shop ledger jammed. Please try again.", ephemeral=True)
            return
        await interaction.edit_original_response(embed=build_purchase_embed(purchase), view=self.compact_view())

    def compact_view(self) -> PostExplorationView:
        return PostExplorationView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
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

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_defense_selector(interaction)

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary)
    async def shop(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_shop(interaction)

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
                defense_service=self.defense_service,
                shop_service=self.shop_service,
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
        await interaction.response.defer()
        report = None
        with self.session_factory() as db:
            player = self.exploration_service.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            report = self.defense_service.resolve_if_expired(db, player)
            state = self.exploration_service.energy.recalculate(player)
            profile_embed = embed(interaction.user.display_name, title_for_player(player), colour=WARM_GOLD)
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
        await interaction.edit_original_response(embed=profile_embed, view=self.compact_view())

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
            cooldown_seconds = get_explore_cooldown_minutes(player.explore_level) * 60
            db.commit()
        response = embed("Dungeon Energy", colour=MIDNIGHT_BLUE)
        response.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
        response.add_field(name="Regeneration", value=f"1 energy every {human_duration(cooldown_seconds)}")
        response.add_field(name="Explorations Available", value=str(state.energy))
        response.add_field(name="Next Energy", value=discord_relative_timestamp(state.next_energy_at))
        response.add_field(name="Full Energy", value=discord_relative_timestamp(state.full_energy_at))
        response.set_footer(text=f"Energy cap: {MAX_ENERGY} | Explore Level: {player.explore_level}")
        await interaction.response.edit_message(embed=response, view=self.compact_view())

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary, row=0)
    async def shop(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_shop(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success, row=1)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_defense_selector(interaction)

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
        await interaction.response.edit_message(embed=help_embed, view=self.compact_view())


class DefenseLevelSelectView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
        )
        self.add_item(DefenseLevelSelect())

    async def start_defense(self, interaction: discord.Interaction, dungeon_level: int) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Defending only works in a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                started = self.defense_service.start(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                    dungeon_level=dungeon_level,
                    channel_id=interaction.channel_id,
                    message_id=interaction.message.id if interaction.message else None,
                )
                db.commit()
        except AlreadyDefendingError:
            await interaction.followup.send("You are already defending.", ephemeral=True)
            return
        except InvalidDungeonLevelError:
            await interaction.followup.send("Choose a dungeon level from 1 through 20.", ephemeral=True)
            return
        except Exception:
            log.exception("Defense selector failed")
            await interaction.followup.send("The guard roster fell off the wall. Please try again.", ephemeral=True)
            return
        await interaction.edit_original_response(embed=build_defense_started_embed(started), view=self.compact_view())

    @discord.ui.button(label="Stop Defending", style=discord.ButtonStyle.danger, row=1)
    async def stop_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.stop_defending(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            embed=build_hall_embed(),
            view=StewardsHallView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
            ),
        )


class DefenseLevelSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=f"Level {level}",
                value=str(level),
                description=_defense_level_description(level),
            )
            for level in range(1, 21)
        ]
        super().__init__(
            placeholder="Choose dungeon level",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DefenseLevelSelectView):
            await interaction.response.send_message("This defense selector is no longer available.", ephemeral=True)
            return
        await view.start_defense(interaction, int(self.values[0]))


def _defense_level_description(level: int) -> str:
    if level <= 5:
        return "Low risk, modest rewards"
    if level <= 10:
        return "Growing pressure and better rewards"
    if level <= 15:
        return "Dangerous enemies and strong rewards"
    return "Severe danger, richest rewards"


class ShopView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
        )
        for number in range(1, 11):
            self.add_item(ShopBuyButton(number))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            embed=build_hall_embed(),
            view=StewardsHallView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
            ),
        )


class ShopBuyButton(discord.ui.Button):
    def __init__(self, stock_number: int) -> None:
        super().__init__(
            label=str(stock_number),
            style=discord.ButtonStyle.primary,
            row=0 if stock_number <= 5 else 1,
            custom_id=f"shop:buy:{stock_number}",
        )
        self.stock_number = stock_number

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ShopView):
            await interaction.response.send_message("This shop is no longer available.", ephemeral=True)
            return
        await view.buy_shop_item(interaction, self.stock_number)
