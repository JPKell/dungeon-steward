from __future__ import annotations

import logging
import random

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
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService, banner_first_message_payload
from bot.services.discord_emoji_service import DEFAULT_DISCORD_EMOJIS, DiscordEmojiService
from bot.services.dungeon_progression_service import (
    get_player_dungeon_unlock_state,
    sync_player_dungeon_progression,
)
from bot.services.encounter_service import Encounter
from bot.services.enemy_service import DUNGEON_LEVEL_MAX, DUNGEON_LEVEL_MIN
from bot.services.energy_service import InsufficientEnergyError
from bot.services.equipment_service import EQUIPMENT_SLOTS, EquipmentItem, get_effective_combat_stats
from bot.services.exploration_service import (
    ExplorationAlreadyResolvedError,
    ExplorationExpiredError,
    ExplorationNotOwnedError,
    ExplorationService,
)
from bot.services.location_service import LOCATION_SERVICE
from bot.services.potion_service import (
    POTION_TYPE_EMOJIS,
    ActivePotion,
    PotionActiveSlotLimitError,
    PotionInventoryEntry,
    PotionItem,
    PotionNotOwnedError,
    PotionReplacementRequired,
    PotionService,
)
from bot.services.progression_service import allocate_stat_points, get_explore_cooldown_minutes, sync_combat_progression
from bot.services.shop_service import (
    InsufficientGoldError,
    InvalidShopSelectionError,
    ShopPurchaseQuote,
    ShopService,
    ShopStock,
)
from bot.utils.defense_embeds import build_defense_report_embed, build_defense_started_embed
from bot.utils.embeds import DEEP_NAVY, MIDNIGHT_BLUE, WARM_GOLD, embed
from bot.utils.emoji import equipment_emoji, gold_emoji, rarity_badge_emoji
from bot.utils.helpers import EM_SPACE, format_gold, format_item_stats, influence_value
from bot.utils.profile_embeds import build_profile_embed
from bot.utils.shop_embeds import build_purchase_embed, build_shop_embed
from bot.utils.time import discord_relative_timestamp, human_duration, utc_now

log = logging.getLogger(__name__)

STAT_ALLOCATION_PROFILE = "profile"
STAT_ALLOCATION_SUMMARY = "summary"
STAT_BUTTONS = (
    ("attack", "ATK +1"),
    ("defense", "DEF +1"),
    ("speed", "SPD +1"),
)
POTION_FULL_INVENTORY_NOTE = (
    "Potion limit reached. Your body is blinking every warning light it has; "
    "wait for one potion to expire before consuming another."
)
STAT_LABELS = {
    "attack": "ATK",
    "defense": "DEF",
    "speed": "SPD",
}
DEFENSE_CONTINUE_DESTINATIONS = {
    "hall": "Continue to Hall",
    "shop": "Continue to Shop",
}
POTION_PAGE_SIZE = 10


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
        choices = list(encounter.choices)
        random.shuffle(choices)
        for choice in choices:
            self.add_item(ExplorationButton(choice.key, choice.label))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message("This expedition belongs to another player.", ephemeral=True)
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
                "The dungeon coughed up the magic blue smoke. Something is wrong with the dungeon. Please try again.",
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
        if result.potion_drop:
            DEFAULT_DISCORD_ASSETS.apply_thumbnail(result_embed, result.potion_drop.thumbnail_asset)
            emoji = _potion_marker(result.potion_drop, DEFAULT_DISCORD_EMOJIS)
            result_embed.add_field(name="Potion Found", value=f"{emoji} **{result.potion_drop.name}** x1", inline=False)
        if result.leveled_up:
            result_embed.add_field(name="Explore Level Up", value="Your dungeon title grows heavier.", inline=False)
        if result.energy_state.next_energy_at:
            result_embed.add_field(
                name="Next Energy",
                value=human_duration(result.energy_state.seconds_until_next),
            )
        DEFAULT_DISCORD_ASSETS.apply_banner(result_embed, LOCATION_SERVICE.banner_asset_for("explore_results"))
        await interaction.edit_original_response(
            **banner_first_message_payload(result_embed, attachment_parameter="attachments"),
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


def build_hall_embed(
    *,
    dungeon=None,
    objective=None,
    contributor_count: int = 0,
    player_contribution: int = 0,
    player_qualifies: bool | None = None,
    estimated_reward: int | None = None,
    contribution_leaders: list[tuple[str, int]] | None = None,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
    emoji_service: DiscordEmojiService = DEFAULT_DISCORD_EMOJIS,
) -> discord.Embed:
    
    # Description section
    hall = embed(
        "Steward's Hall",
        (
            "The Steward's Hall is the dungeon's nerve center: a long chamber of annotated maps, "
            "ledger chains, brass speaking tubes, and candlelit tables where every expedition, guard "
            "shift, and questionable renovation eventually becomes paperwork.\nDungeon stability will "
            "affect the dungeon's performance in combat and exploration. Keep the dungeon stable to "
            "avoid missing out on gold and xp."
        ),
        colour=DEEP_NAVY,
    )

    # Community dungeon stats 
    if dungeon is not None:
        hall.add_field(name="\u200b", value="**Shared community dungeon**", inline=False)
        hall.add_field(name="Level", value=str(dungeon.level))
        hall.add_field(name="Gold", value=format_gold(dungeon.gold))
        hall.add_field(name="Stability", value=f"{dungeon.stability}/100")
        hall.add_field(name="Influence", value=influence_value(dungeon.hero_influence, dungeon.villain_influence, emoji_service))
    
    # Spacer
    hall.add_field(name="\u200b", value="", inline=False)

    if objective is not None:
        objective_description = getattr(objective, "description", "")
        target = max(1, int(objective.target_value))
        displayed_progress = min(target, int(objective.progress_value or 0))
        percent = min(100.0, (displayed_progress / target) * 100)
        hall.add_field(
            name=f"Weekly Objective: {objective.title}",
            value=(
                f"{objective_description}\n"
                f"Progress: {displayed_progress}/{target} ({percent:.0f}%) | "
                f"Ends {discord_relative_timestamp(objective.ends_at)}"
            ),
            inline=False,
        )
        hall.add_field(name="Mode", value=str(getattr(objective, "mode", "mixed")).title())
        hall.add_field(name="Contributors", value=str(contributor_count))
        hall.add_field(name="Difficulty", value=f"{float(getattr(objective, 'difficulty_index', 1.0)):.2f}x")
        if contribution_leaders:
            lines = [
                f"{index}. {name}: {value} ({min(100.0, (value / target) * 100):.0f}%)"
                for index, (name, value) in enumerate(contribution_leaders[:5], start=1)
            ]
            hall.add_field(name="Contribution Leaders", value="\n".join(lines), inline=False)

        if player_qualifies is not None:
            qualification = "Qualifies" if player_qualifies else "Not qualified"
            reward_text = f" | Est. reward {format_gold(estimated_reward)}" if estimated_reward is not None else ""
            hall.add_field(
                name="Your Contribution",
                value=f"{player_contribution}/{target} | {qualification}{reward_text}",
                inline=False,
            )
    asset_service.apply_banner(hall, LOCATION_SERVICE.banner_asset_for("stewards_hall"))
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
        is_defending: bool = False,
        stat_allocation_context: str | None = None,
        allow_defense_return_button: bool = True,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.exploration_service = exploration_service
        self.defense_service = defense_service
        self.shop_service = shop_service
        self.potion_service = getattr(exploration_service, "potions", None) or PotionService()
        self.owner_user_id = owner_user_id
        self.is_defending = is_defending
        self.stat_allocation_context = stat_allocation_context
        self.allow_defense_return_button = allow_defense_return_button
        self._apply_defense_button_state()
        if stat_allocation_context is not None:
            self._add_stat_allocation_buttons()

    def _apply_defense_button_state(self) -> None:
        for item in tuple(self.children):
            if not isinstance(item, discord.ui.Button) or item.label != "Defend":
                continue
            if self.is_defending:
                if self.allow_defense_return_button:
                    item.label = "Return from Dungeon"
                    item.style = discord.ButtonStyle.danger
                else:
                    self.remove_item(item)
            else:
                item.style = discord.ButtonStyle.success

    def _add_stat_allocation_buttons(self) -> None:
        for stat, label in STAT_BUTTONS:
            self.add_item(StatAllocationButton(stat, label))

    async def _edit_current_response(self, interaction: discord.Interaction, **kwargs) -> None:
        response = getattr(interaction, "response", None)
        is_done = False
        if response is not None:
            response_is_done = getattr(response, "is_done", None)
            if callable(response_is_done):
                is_done = response_is_done()
        if response is not None and not is_done and hasattr(response, "edit_message"):
            await response.edit_message(**kwargs)
            return
        await interaction.edit_original_response(**kwargs)

    async def _send_navigation_error(self, interaction: discord.Interaction, message: str) -> None:
        response = getattr(interaction, "response", None)
        is_done = False
        if response is not None:
            response_is_done = getattr(response, "is_done", None)
            if callable(response_is_done):
                is_done = response_is_done()
        if response is not None and not is_done and hasattr(response, "send_message"):
            await response.send_message(message, ephemeral=True)
            return
        await interaction.followup.send(message, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "These dungeon controls belong to another player.",
                ephemeral=True,
            )
            return False
        return True

    async def allocate_stat_point(self, interaction: discord.Interaction, stat: str) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Stats are server-specific.", ephemeral=True)
            return
        await interaction.response.defer()
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
                    player = self.exploration_service.players.get_or_create(
                        db,
                        guild_id=interaction.guild_id,
                        user_id=interaction.user.id,
                        display_name=interaction.user.display_name,
                    )
                allocate_stat_points(player, stat, 1)
                sync_combat_progression(player)
                state = self.exploration_service.energy.recalculate(player)
                stats = get_effective_combat_stats(player)
                db.commit()
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            log.exception("Stat allocation button failed")
            await interaction.followup.send("The stat ledger jammed. Please try again.", ephemeral=True)
            return

        next_context = self.stat_allocation_context if player.unspent_stat_points > 0 else None
        next_view = self.compact_view(
            is_defending=player.is_defending,
            stat_allocation_context=next_context,
        )
        if self.stat_allocation_context == STAT_ALLOCATION_PROFILE:
            response = build_profile_embed(
                display_name=interaction.user.display_name,
                player=player,
                energy_state=state,
                stats=stats,
            )
        else:
            response = _stat_allocation_summary_embed(
                interaction,
                stat=stat,
                remaining_points=player.unspent_stat_points,
            )
        await interaction.edit_original_response(
            **banner_first_message_payload(response, attachment_parameter="attachments"),
            view=next_view,
        )

    async def start_exploration(self, interaction: discord.Interaction, dungeon_level: int = 1) -> None:
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
                    dungeon_level=dungeon_level,
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
            out_of_energy = embed(
                "Out of Energy",
                "You do not currently have enough energy to explore.",
                colour=MIDNIGHT_BLUE,
            )
            out_of_energy.add_field(name="Energy", value=f"{state.energy}/{MAX_ENERGY}")
            out_of_energy.add_field(name="Next Energy", value=human_duration(state.seconds_until_next))
            out_of_energy.add_field(
                name="Regeneration",
                value=f"1 energy every {human_duration(cooldown_seconds)}",
                inline=False,
            )
            DEFAULT_DISCORD_ASSETS.apply_banner(out_of_energy, LOCATION_SERVICE.banner_asset_for("out_of_energy"))
            await interaction.followup.send(
                **banner_first_message_payload(out_of_energy),
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
        DEFAULT_DISCORD_ASSETS.apply_banner(encounter_embed, LOCATION_SERVICE.banner_asset_for("explore_dungeon"))
        await interaction.edit_original_response(
            **banner_first_message_payload(encounter_embed, attachment_parameter="attachments"),
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

    async def show_exploration_selector(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Dungeon expeditions only work in a server.",
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
            sync_player_dungeon_progression(player)
            options = _dungeon_select_options(player)
            active = self.potion_service.active_effects_at(db, player)
            potion_entries = self.potion_service.inventory_entries(db, player)
            db.commit()
        selector = _build_dungeon_level_selector_embed(
            title="Choose Dungeon Level",
            description="Select an unlocked dungeon level, then descend when ready.",
            potion_service=self.potion_service,
            active=active,
            potion_entries=potion_entries,
            potion_page=0,
            banner_key="dungeon_selection",
        )
        await interaction.response.edit_message(
            **banner_first_message_payload(selector, attachment_parameter="attachments"),
            view=ExploreLevelSelectView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
                options=options,
                active=active,
                potion_entries=potion_entries,
                is_defending=self.is_defending,
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
            report_embed = build_defense_report_embed(report)
            await interaction.followup.send(
                **banner_first_message_payload(report_embed, view=self.defense_report_view(report)),
            )
            return False
        return True

    async def resolve_expired_defense_before_navigation(
        self,
        interaction: discord.Interaction,
        *,
        continue_destination: str,
    ) -> bool:
        if interaction.guild_id is None:
            return True
        try:
            with self.session_factory() as db:
                player = self.exploration_service.players.get_or_create(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                report = self.defense_service.resolve_if_expired(db, player)
                db.commit()
        except Exception:
            log.exception("Failed to resolve expired defense before navigation")
            await self._send_navigation_error(
                interaction,
                "The defense ledger would not close cleanly. Please try again.",
            )
            return False
        if report is None:
            return True
        report_embed = build_defense_report_embed(report)
        await self._edit_current_response(
            interaction,
            **banner_first_message_payload(
                report_embed,
                attachment_parameter="attachments",
                view=self.defense_report_view(report, continue_destination=continue_destination),
            ),
        )
        return False

    async def show_defense_selector(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Defending only works in a server.", ephemeral=True)
            return
        with self.session_factory() as db:
            player = self.exploration_service.players.get_or_create(
                db,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
            )
            sync_player_dungeon_progression(player)
            options = _dungeon_select_options(player)
            active = self.potion_service.active_effects_at(db, player)
            potion_entries = self.potion_service.inventory_entries(db, player)
            db.commit()
        selector = _build_dungeon_level_selector_embed(
            title="Choose Defense Level",
            description="Select any unlocked dungeon level. Higher levels pay better and hit harder.",
            potion_service=self.potion_service,
            active=active,
            potion_entries=potion_entries,
            potion_page=0,
            banner_key="defend",
        )
        await interaction.response.edit_message(
            **banner_first_message_payload(selector, attachment_parameter="attachments"),
            view=DefenseLevelSelectView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
                options=options,
                active=active,
                potion_entries=potion_entries,
                is_defending=self.is_defending,
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
        report_embed = build_defense_report_embed(report)
        await interaction.followup.send(
            **banner_first_message_payload(report_embed, view=self.defense_report_view(report)),
        )
        await interaction.edit_original_response(view=self.compact_view(is_defending=False))

    async def show_shop(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("The shop is server-specific.", ephemeral=True)
            return
        if not await self.resolve_expired_defense_before_navigation(interaction, continue_destination="shop"):
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
            **banner_first_message_payload(shop_embed, attachment_parameter="attachments"),
            view=ShopView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
                is_defending=self.is_defending,
                stock=stock,
                player=player,
                emoji_service=DEFAULT_DISCORD_EMOJIS,
            ),
        )

    async def preview_shop_item(self, interaction: discord.Interaction, stock_number: int) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("The shop is server-specific.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                player = self.exploration_service.players.get_or_create(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                stock = self.shop_service.stock_for_player(player)
                selected_quote = self.shop_service.quote_stock_item(player, stock=stock, stock_number=stock_number)
                db.commit()
                shop_embed = build_shop_embed(
                    stock,
                    player=player,
                    equipment=self.shop_service.equipment,
                    selected_quote=selected_quote,
                )
        except InvalidShopSelectionError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            log.exception("Shop selector failed")
            await interaction.followup.send("The shop ledger jammed. Please try again.", ephemeral=True)
            return
        await interaction.edit_original_response(
            **banner_first_message_payload(shop_embed, attachment_parameter="attachments"),
            view=ShopView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
                is_defending=self.is_defending,
                stock=stock,
                player=player,
                selected_stock_number=stock_number,
                emoji_service=DEFAULT_DISCORD_EMOJIS,
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
        purchase_embed = build_purchase_embed(purchase)
        await interaction.edit_original_response(
            **banner_first_message_payload(purchase_embed, attachment_parameter="attachments"),
            view=self.compact_view(),
        )

    async def show_inventory(self, interaction: discord.Interaction, *, origin: str = "hall") -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Inventory is server-specific.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                player = self.exploration_service.players.get_or_create(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                now = utc_now()
                active = self.potion_service.active_effects_at(db, player, now)
                entries = self.potion_service.inventory_entries(db, player)
                inventory_embed = _build_potion_inventory_embed(
                    potion_service=self.potion_service,
                    entries=entries,
                    active=active,
                    page=0,
                )
                inventory_view = PotionInventoryView(
                    session_factory=self.session_factory,
                    exploration_service=self.exploration_service,
                    defense_service=self.defense_service,
                    shop_service=self.shop_service,
                    owner_user_id=self.owner_user_id,
                    origin=origin,
                    entries=entries,
                    active=active,
                    is_defending=player.is_defending,
                )
                db.commit()
        except Exception:
            log.exception("Potion inventory button failed")
            await interaction.followup.send("The potion satchel would not open. Please try again.", ephemeral=True)
            return
        await interaction.edit_original_response(
            **banner_first_message_payload(inventory_embed, attachment_parameter="attachments"),
            view=inventory_view,
        )

    async def consume_potion(
        self,
        interaction: discord.Interaction,
        item_key: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Inventory is server-specific.", ephemeral=True)
            return
        await interaction.response.defer()
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
                    raise PotionNotOwnedError("You do not have any potions yet.")
                self.potion_service.consume(
                    db,
                    player,
                    item_key,
                    idempotency_token=str(interaction.id),
                    now=utc_now(),
                )
                active = self.potion_service.active_effects_at(db, player)
                entries = self.potion_service.inventory_entries(db, player)
                response_embed, response_view = self._potion_consume_response(
                    entries=entries,
                    active=active,
                    is_defending=player.is_defending,
                )
                db.commit()
        except PotionReplacementRequired as error:
            await interaction.followup.send(
                f"{error.active.item.name} is already active. Wait for it to run out before using another "
                f"{error.requested.effect_group.replace('_', ' ')} potion.",
                ephemeral=True,
            )
            return
        except PotionActiveSlotLimitError as error:
            active_names = ", ".join(active.item.name for active in error.active) or "none"
            await interaction.followup.send(f"You already have three potion groups active: {active_names}.", ephemeral=True)
            return
        except PotionNotOwnedError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            log.exception("Potion consume failed")
            await interaction.followup.send("The potion cork would not budge. Please try again.", ephemeral=True)
            return
        await interaction.edit_original_response(
            **banner_first_message_payload(response_embed, attachment_parameter="attachments"),
            view=response_view,
        )

    def _potion_consume_response(
        self,
        *,
        entries: tuple[PotionInventoryEntry, ...],
        active: tuple[ActivePotion, ...],
        is_defending: bool,
    ) -> tuple[discord.Embed, discord.ui.View]:
        inventory_embed = _build_potion_inventory_embed(
            potion_service=self.potion_service,
            entries=entries,
            active=active,
            page=getattr(self, "potion_page", 0),
        )
        inventory_view = PotionInventoryView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            origin=getattr(self, "origin", "hall"),
            entries=entries,
            active=active,
            is_defending=is_defending,
            page=getattr(self, "potion_page", 0),
        )
        return inventory_embed, inventory_view

    def compact_view(
        self,
        *,
        is_defending: bool | None = None,
        stat_allocation_context: str | None = None,
        allow_defense_return_button: bool = True,
        include_explore: bool = True,
        include_shop: bool = True,
    ) -> PostExplorationView:
        return PostExplorationView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            is_defending=self.is_defending if is_defending is None else is_defending,
            stat_allocation_context=stat_allocation_context,
            allow_defense_return_button=allow_defense_return_button,
            include_explore=include_explore,
            include_shop=include_shop,
        )

    def defense_report_view(self, report, *, continue_destination: str | None = None) -> DefenseResolvedActionView:
        stat_context = STAT_ALLOCATION_SUMMARY if report.stat_points_earned > 0 else None
        return DefenseResolvedActionView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            stat_allocation_context=stat_context,
            continue_destination=continue_destination,
        )

    async def show_hall(self, interaction: discord.Interaction, *, is_defending: bool | None = None) -> None:
        if interaction.guild_id is None:
            hall_embed = build_hall_embed()
        else:
            if not await self.resolve_expired_defense_before_navigation(interaction, continue_destination="hall"):
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
                player = self.exploration_service.players.get_or_create(
                    db,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    display_name=interaction.user.display_name,
                )
                contributor_count = self.exploration_service.weekly._participant_count(db, objective)
                player_contribution = self.exploration_service.weekly.player_contribution(db, objective, player_id=player.id)
                player_qualifies = self.exploration_service.weekly.qualifies_for_reward(objective, player_contribution)
                estimated_reward = self.exploration_service.weekly.reward_preview(player, objective).gold_awarded
                contribution_leaders = [
                    (name, value)
                    for name, value in self.exploration_service.weekly.contribution_rows(db, objective, limit=5)
                ]
                db.commit()
                hall_embed = build_hall_embed(
                    dungeon=dungeon,
                    objective=objective,
                    contributor_count=contributor_count,
                    player_contribution=player_contribution,
                    player_qualifies=player_qualifies,
                    estimated_reward=estimated_reward,
                    contribution_leaders=contribution_leaders,
                )
        await interaction.response.edit_message(
            **banner_first_message_payload(hall_embed, attachment_parameter="attachments"),
            view=StewardsHallView(
                session_factory=self.session_factory,
                exploration_service=self.exploration_service,
                defense_service=self.defense_service,
                shop_service=self.shop_service,
                owner_user_id=self.owner_user_id,
                is_defending=self.is_defending if is_defending is None else is_defending,
            ),
        )


class StatAllocationButton(discord.ui.Button):
    def __init__(self, stat: str, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=2, custom_id=f"stats:add:{stat}")
        self.stat = stat

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DungeonActionView):
            await interaction.response.send_message("These stat controls are no longer available.", ephemeral=True)
            return
        await view.allocate_stat_point(interaction, self.stat)


class PostExplorationView(DungeonActionView):
    def __init__(self, *args, include_explore: bool = True, include_shop: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not include_explore:
            for child in tuple(self.children):
                if isinstance(child, discord.ui.Button) and child.label == "Explore":
                    self.remove_item(child)
        if not include_shop:
            for child in tuple(self.children):
                if isinstance(child, discord.ui.Button) and child.label == "Shop":
                    self.remove_item(child)

    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary, row=0)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success, row=0)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if self.is_defending:
            await self.stop_defending(interaction)
            return
        await self.show_defense_selector(interaction)

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary, row=0)
    async def shop(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_shop(interaction)

    @discord.ui.button(label="Steward's Hall", style=discord.ButtonStyle.secondary, row=0)
    async def hall(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_hall(interaction)


class DefenseResolvedActionView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
        is_defending: bool = False,
        stat_allocation_context: str | None = None,
        allow_defense_return_button: bool = True,
        continue_destination: str | None = None,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
            is_defending=is_defending,
            stat_allocation_context=stat_allocation_context,
            allow_defense_return_button=allow_defense_return_button,
        )
        self.continue_destination = continue_destination
        if continue_destination in DEFENSE_CONTINUE_DESTINATIONS:
            self.add_item(DefenseContinueButton(continue_destination, DEFENSE_CONTINUE_DESTINATIONS[continue_destination]))

    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary, row=0)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success, row=0)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_defense_selector(interaction)

    @discord.ui.button(label="Steward's Hall", style=discord.ButtonStyle.secondary, row=0)
    async def hall(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_hall(interaction, is_defending=False)


class DefenseContinueButton(discord.ui.Button):
    def __init__(self, destination: str, label: str) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            row=0,
            custom_id=f"defense:continue:{destination}",
        )
        self.destination = destination

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DefenseResolvedActionView):
            await interaction.response.send_message("This defense report is no longer available.", ephemeral=True)
            return
        if self.destination == "shop":
            await view.show_shop(interaction)
            return
        if self.destination == "hall":
            await view.show_hall(interaction, is_defending=False)
            return
        await interaction.response.send_message("That destination is no longer available.", ephemeral=True)


class StewardsHallView(DungeonActionView):
    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary, row=0)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success, row=0)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if self.is_defending:
            await self.stop_defending(interaction)
            return
        await self.show_defense_selector(interaction)

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
            sync_combat_progression(player)
            stats = get_effective_combat_stats(player)
            db.commit()
            profile_embed = build_profile_embed(
                display_name=interaction.user.display_name,
                player=player,
                energy_state=state,
                stats=stats,
            )
        if report is not None:
            report_embed = build_defense_report_embed(report)
            await interaction.followup.send(
                **banner_first_message_payload(report_embed, view=self.defense_report_view(report)),
            )
        stat_context = STAT_ALLOCATION_PROFILE if player.unspent_stat_points > 0 else None
        await interaction.edit_original_response(
            **banner_first_message_payload(profile_embed, attachment_parameter="attachments"),
            view=self.compact_view(
                is_defending=player.is_defending,
                stat_allocation_context=stat_context,
                include_shop=False,
            ),
        )

    @discord.ui.button(label="Inventory", style=discord.ButtonStyle.secondary, row=0)
    async def inventory(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_inventory(interaction, origin="hall")

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary, row=0)
    async def shop(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_shop(interaction)

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
            board.description = "\n".join(f"{index}. {name}: {value} XP" for index, (name, value) in enumerate(rows, start=1))
        else:
            board.description = "No entries yet. The dungeon awaits its first questionable decision."
        DEFAULT_DISCORD_ASSETS.apply_banner(board, LOCATION_SERVICE.banner_asset_for("leaderboard"))
        await interaction.response.edit_message(
            **banner_first_message_payload(board, attachment_parameter="attachments"),
            view=self.compact_view(include_shop=False),
        )

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
            "\nDefending resolves one attack per completed minute and awards Combat XP and gold. "
            "The equipment shop refreshes hourly by Combat Level. "
            "Weekly objectives give the whole server a reason to keep returning."
        )
        help_embed.add_field(
            name="Commands",
            value=(
                "/dungeon explore\n/dungeon defend\n/dungeon stop-defending\n"
                "/dungeon shop\n/dungeon profile\n"
                "/dungeon inventory\n/dungeon hall\n/dungeon leaderboard"
            ),
            inline=False,
        )
        help_embed.add_field(name="Version", value=__version__)
        DEFAULT_DISCORD_ASSETS.apply_banner(help_embed, LOCATION_SERVICE.banner_asset_for("dungeon_help"))
        await interaction.response.edit_message(
            **banner_first_message_payload(help_embed, attachment_parameter="attachments"),
            view=self.compact_view(include_shop=False),
        )


class DefenseLevelSelectView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
        options: list[discord.SelectOption],
        active: tuple[ActivePotion, ...] = (),
        potion_entries: tuple[PotionInventoryEntry, ...] = (),
        potion_page: int = 0,
        is_defending: bool = False,
        selected_dungeon_level: int | None = None,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
            is_defending=is_defending,
            allow_defense_return_button=False,
        )
        self.origin = "defense"
        self.options = options
        self.active = active
        self.potion_entries = potion_entries
        self.potion_page = _clamp_potion_page(potion_page, len(potion_entries))
        self.selected_dungeon_level = selected_dungeon_level
        self.add_item(DefenseLevelSelect(options, selected_dungeon_level=selected_dungeon_level))
        if _show_level_select_potion_controls(active, potion_entries):
            self.add_item(PotionConsumeSelect(_potion_page_entries(potion_entries, self.potion_page), row=1))
            _add_potion_page_buttons(self, potion_entries=potion_entries, page=self.potion_page, row=2)
        self.add_item(DefenseDescendButton(disabled=selected_dungeon_level is None))

    def select_dungeon_level(self, dungeon_level: int) -> None:
        self.selected_dungeon_level = dungeon_level
        for child in self.children:
            if isinstance(child, DefenseLevelSelect):
                for option in child.options:
                    option.default = option.value == str(dungeon_level)
                child.placeholder = f"Level {dungeon_level} selected"
            elif isinstance(child, DefenseDescendButton):
                child.disabled = False

    async def change_potion_page(self, interaction: discord.Interaction, page: int) -> None:
        next_page = _clamp_potion_page(page, len(self.potion_entries))
        selector = _build_dungeon_level_selector_embed(
            title="Choose Defense Level",
            description="Select any unlocked dungeon level. Higher levels pay better and hit harder.",
            potion_service=self.potion_service,
            active=self.active,
            potion_entries=self.potion_entries,
            potion_page=next_page,
            banner_key="defend",
        )
        next_view = DefenseLevelSelectView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            options=self.options,
            active=self.active,
            potion_entries=self.potion_entries,
            potion_page=next_page,
            is_defending=self.is_defending,
            selected_dungeon_level=self.selected_dungeon_level,
        )
        await interaction.response.edit_message(
            **banner_first_message_payload(selector, attachment_parameter="attachments"),
            view=next_view,
        )

    def _potion_consume_response(
        self,
        *,
        entries: tuple[PotionInventoryEntry, ...],
        active: tuple[ActivePotion, ...],
        is_defending: bool,
    ) -> tuple[discord.Embed, discord.ui.View]:
        next_page = _clamp_potion_page(self.potion_page, len(entries))
        selector = _build_dungeon_level_selector_embed(
            title="Choose Defense Level",
            description="Select any unlocked dungeon level. Higher levels pay better and hit harder.",
            potion_service=self.potion_service,
            active=active,
            potion_entries=entries,
            potion_page=next_page,
            banner_key="defend",
        )
        next_view = DefenseLevelSelectView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            options=self.options,
            active=active,
            potion_entries=entries,
            potion_page=next_page,
            is_defending=is_defending,
            selected_dungeon_level=self.selected_dungeon_level,
        )
        return selector, next_view

    async def start_defense(self, interaction: discord.Interaction, dungeon_level: int) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Defending only works in a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                result = self.defense_service.start_after_resolving(
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
        if result.resolved_previous is not None:
            report_embed = build_defense_report_embed(result.resolved_previous)
            await interaction.followup.send(
                **banner_first_message_payload(
                    report_embed,
                    view=self.defense_report_view(result.resolved_previous),
                ),
            )
        started_embed = build_defense_started_embed(result.started)
        await interaction.edit_original_response(
            **banner_first_message_payload(started_embed, attachment_parameter="attachments"),
            view=self.compact_view(
                is_defending=True,
                allow_defense_return_button=False,
                include_explore=False,
                include_shop=False,
            ),
        )

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_hall(interaction)


class DefenseLevelSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], *, selected_dungeon_level: int | None = None) -> None:
        for option in options:
            option.default = option.value == str(selected_dungeon_level)
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
        view.select_dungeon_level(int(self.values[0]))
        await interaction.response.edit_message(view=view)


class DefenseDescendButton(discord.ui.Button):
    def __init__(self, *, disabled: bool) -> None:
        super().__init__(
            label="Descend into the dungeon",
            style=discord.ButtonStyle.primary,
            disabled=disabled,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DefenseLevelSelectView):
            await interaction.response.send_message("This defense selector is no longer available.", ephemeral=True)
            return
        if view.selected_dungeon_level is None:
            await interaction.response.send_message("Choose a dungeon level first.", ephemeral=True)
            return
        await view.start_defense(interaction, view.selected_dungeon_level)


class ExploreLevelSelectView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
        options: list[discord.SelectOption],
        active: tuple[ActivePotion, ...] = (),
        potion_entries: tuple[PotionInventoryEntry, ...] = (),
        potion_page: int = 0,
        is_defending: bool = False,
        selected_dungeon_level: int | None = None,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
            is_defending=is_defending,
            allow_defense_return_button=False,
        )
        self.origin = "explore"
        self.options = options
        self.active = active
        self.potion_entries = potion_entries
        self.potion_page = _clamp_potion_page(potion_page, len(potion_entries))
        self.selected_dungeon_level = selected_dungeon_level
        self.add_item(ExploreLevelSelect(options, selected_dungeon_level=selected_dungeon_level))
        if _show_level_select_potion_controls(active, potion_entries):
            self.add_item(PotionConsumeSelect(_potion_page_entries(potion_entries, self.potion_page), row=1))
            _add_potion_page_buttons(self, potion_entries=potion_entries, page=self.potion_page, row=2)
        self.add_item(ExploreDescendButton(disabled=selected_dungeon_level is None))

    def select_dungeon_level(self, dungeon_level: int) -> None:
        self.selected_dungeon_level = dungeon_level
        for child in self.children:
            if isinstance(child, ExploreLevelSelect):
                for option in child.options:
                    option.default = option.value == str(dungeon_level)
                child.placeholder = f"Level {dungeon_level} selected"
            elif isinstance(child, ExploreDescendButton):
                child.disabled = False

    async def change_potion_page(self, interaction: discord.Interaction, page: int) -> None:
        next_page = _clamp_potion_page(page, len(self.potion_entries))
        selector = _build_dungeon_level_selector_embed(
            title="Choose Dungeon Level",
            description="Select an unlocked dungeon level, then descend when ready.",
            potion_service=self.potion_service,
            active=self.active,
            potion_entries=self.potion_entries,
            potion_page=next_page,
            banner_key="dungeon_selection",
        )
        next_view = ExploreLevelSelectView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            options=self.options,
            active=self.active,
            potion_entries=self.potion_entries,
            potion_page=next_page,
            is_defending=self.is_defending,
            selected_dungeon_level=self.selected_dungeon_level,
        )
        await interaction.response.edit_message(
            **banner_first_message_payload(selector, attachment_parameter="attachments"),
            view=next_view,
        )

    def _potion_consume_response(
        self,
        *,
        entries: tuple[PotionInventoryEntry, ...],
        active: tuple[ActivePotion, ...],
        is_defending: bool,
    ) -> tuple[discord.Embed, discord.ui.View]:
        next_page = _clamp_potion_page(self.potion_page, len(entries))
        selector = _build_dungeon_level_selector_embed(
            title="Choose Dungeon Level",
            description="Select an unlocked dungeon level, then descend when ready.",
            potion_service=self.potion_service,
            active=active,
            potion_entries=entries,
            potion_page=next_page,
            banner_key="dungeon_selection",
        )
        next_view = ExploreLevelSelectView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            options=self.options,
            active=active,
            potion_entries=entries,
            potion_page=next_page,
            is_defending=is_defending,
            selected_dungeon_level=self.selected_dungeon_level,
        )
        return selector, next_view

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_hall(interaction)


class ExploreLevelSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], *, selected_dungeon_level: int | None = None) -> None:
        for option in options:
            option.default = option.value == str(selected_dungeon_level)
        super().__init__(
            placeholder="Choose dungeon level",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ExploreLevelSelectView):
            await interaction.response.send_message("This exploration selector is no longer available.", ephemeral=True)
            return
        view.select_dungeon_level(int(self.values[0]))
        await interaction.response.edit_message(view=view)


class ExploreDescendButton(discord.ui.Button):
    def __init__(self, *, disabled: bool) -> None:
        super().__init__(
            label="Descend into the dungeon",
            style=discord.ButtonStyle.primary,
            disabled=disabled,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ExploreLevelSelectView):
            await interaction.response.send_message("This exploration selector is no longer available.", ephemeral=True)
            return
        if view.selected_dungeon_level is None:
            await interaction.response.send_message("Choose a dungeon level first.", ephemeral=True)
            return
        await view.start_exploration(interaction, view.selected_dungeon_level)


def _dungeon_select_options(player: Player) -> list[discord.SelectOption]:
    highest = max(DUNGEON_LEVEL_MIN, int(player.highest_unlocked_dungeon_level or DUNGEON_LEVEL_MIN))
    options: list[discord.SelectOption] = []
    for level in range(DUNGEON_LEVEL_MIN, DUNGEON_LEVEL_MAX + 1):
        unlocked = level <= highest
        if unlocked:
            description = _unlocked_level_description(level)
        else:
            state = get_player_dungeon_unlock_state(player, level)
            description = _locked_level_description(state.missing)
        options.append(
            discord.SelectOption(
                label=f"Level {level}" if unlocked else f"Level {level} locked",
                value=str(level),
                description=description,
            )
        )
        if not unlocked:
            break
    return options


def _unlocked_level_description(level: int) -> str:
    if level <= 5:
        return "Unlocked. Low risk, modest rewards."
    if level <= 10:
        return "Unlocked. Growing pressure and better rewards."
    if level <= 15:
        return "Unlocked. Dangerous enemies and strong rewards."
    return "Unlocked. Severe danger, richest rewards."


def _locked_level_description(missing: tuple[str, ...]) -> str:
    if not missing:
        return "Locked."
    text = "Needs " + "; ".join(missing[:2])
    if len(text) > 100:
        return text[:97] + "..."
    return text


def _stat_allocation_summary_embed(
    interaction: discord.Interaction,
    *,
    stat: str,
    remaining_points: int,
) -> discord.Embed:
    response = _content_embed_from_message(interaction.message) or embed("Stat Point Spent", colour=WARM_GOLD)
    value = f"Added 1 point to {STAT_LABELS.get(stat, stat)}.\nUnspent points: {remaining_points}"
    for index, field in enumerate(response.fields):
        if field.name == "Stat Allocation":
            response.set_field_at(index, name="Stat Allocation", value=value, inline=False)
            break
    else:
        response.add_field(name="Stat Allocation", value=value, inline=False)
    return response


def _content_embed_from_message(message: discord.Message | None) -> discord.Embed | None:
    if message is None or not message.embeds:
        return None
    for candidate in reversed(message.embeds):
        if candidate.title or candidate.description or candidate.fields:
            return candidate.copy()
    return message.embeds[-1].copy()


class PotionInventoryView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
        origin: str,
        entries: tuple[PotionInventoryEntry, ...],
        active: tuple[ActivePotion, ...] = (),
        is_defending: bool = False,
        selected_item_key: str | None = None,
        page: int = 0,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
            is_defending=is_defending,
        )
        self.origin = origin
        self.entries = entries
        self.active = active
        self.selected_item_key = selected_item_key
        self.potion_page = _clamp_potion_page(page, len(entries))
        if entries:
            if len(active) < 3:
                self.add_item(
                    PotionConsumeSelect(
                        _potion_page_entries(entries, self.potion_page),
                        selected_item_key=selected_item_key,
                        placeholder="Select a potion",
                    )
                )
            _add_potion_page_buttons(self, potion_entries=entries, page=self.potion_page, row=1)
        if selected_item_key is not None and len(active) < 3:
            self.add_item(ConsumeSelectedPotionButton(selected_item_key))

    async def change_potion_page(self, interaction: discord.Interaction, page: int) -> None:
        next_page = _clamp_potion_page(page, len(self.entries))
        inventory_embed = _build_potion_inventory_embed(
            potion_service=self.potion_service,
            entries=self.entries,
            active=self.active,
            page=next_page,
        )
        next_view = PotionInventoryView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            origin=self.origin,
            entries=self.entries,
            active=self.active,
            is_defending=self.is_defending,
            page=next_page,
        )
        await interaction.response.edit_message(
            **banner_first_message_payload(inventory_embed, attachment_parameter="attachments"),
            view=next_view,
        )

    async def select_potion(self, interaction: discord.Interaction, item_key: str) -> None:
        next_view = PotionInventoryView(
            session_factory=self.session_factory,
            exploration_service=self.exploration_service,
            defense_service=self.defense_service,
            shop_service=self.shop_service,
            owner_user_id=self.owner_user_id,
            origin=self.origin,
            entries=self.entries,
            active=self.active,
            is_defending=self.is_defending,
            page=self.potion_page,
            selected_item_key=item_key,
        )
        await interaction.response.edit_message(view=next_view)

    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary, row=1)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success, row=1)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if self.is_defending:
            await self.stop_defending(interaction)
            return
        await self.show_defense_selector(interaction)

    @discord.ui.button(label="Steward's Hall", style=discord.ButtonStyle.secondary, row=1)
    async def hall(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_hall(interaction)


class PotionConsumeSelect(discord.ui.Select):
    def __init__(
        self,
        entries: tuple[PotionInventoryEntry, ...],
        *,
        row: int = 0,
        selected_item_key: str | None = None,
        placeholder: str = "Consume a potion",
        emoji_service: DiscordEmojiService | None = None,
    ) -> None:
        emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
        options = [_potion_select_option(entry, emoji_service) for entry in entries]
        for option in options:
            option.default = option.value == selected_item_key
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, PotionInventoryView):
            await view.select_potion(interaction, self.values[0])
            return
        if not isinstance(view, DungeonActionView):
            await interaction.response.send_message("This potion satchel is no longer available.", ephemeral=True)
            return
        await view.consume_potion(interaction, self.values[0])


class ConsumeSelectedPotionButton(discord.ui.Button):
    def __init__(self, item_key: str) -> None:
        super().__init__(
            label="Consume Potion",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        self.item_key = item_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, PotionInventoryView):
            await interaction.response.send_message("This potion button is no longer available.", ephemeral=True)
            return
        await view.consume_potion(interaction, self.item_key)


class PotionPageButton(discord.ui.Button):
    def __init__(
        self,
        *,
        emoji: str,
        delta: int,
        page: int,
        total_entries: int,
        row: int,
    ) -> None:
        target_page = page + delta
        super().__init__(
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            disabled=_clamp_potion_page(target_page, total_entries) == page,
            row=row,
        )
        self.target_page = target_page

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, (PotionInventoryView, DefenseLevelSelectView, ExploreLevelSelectView)):
            await interaction.response.send_message("This potion page is no longer available.", ephemeral=True)
            return
        await view.change_potion_page(interaction, self.target_page)


def _build_potion_inventory_embed(
    *,
    potion_service: PotionService,
    entries: tuple[PotionInventoryEntry, ...],
    active: tuple[ActivePotion, ...],
    page: int = 0,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
    emoji_service: DiscordEmojiService | None = None,
) -> discord.Embed:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    response = embed("Potion Inventory", colour=MIDNIGHT_BLUE)
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("inventory"))
    asset_service.apply_thumbnail(response, _potion_thumbnail_asset(entries=entries, active=active))
    _add_active_potion_fields(response, potion_service=potion_service, active=active, emoji_service=emoji_service)
    response.add_field(name="Slots", value=potion_service.active_slot_usage(active), inline=False)

    _add_potion_inventory_fields(
        response,
        potion_service=potion_service,
        entries=entries,
        page=page,
        emoji_service=emoji_service,
    )

    if len(active) >= potion_service.content.activation_rules.max_simultaneous_effect_groups:
        response.set_footer(text=POTION_FULL_INVENTORY_NOTE)

    return response


def _add_potion_inventory_fields(
    response: discord.Embed,
    *,
    potion_service: PotionService,
    entries: tuple[PotionInventoryEntry, ...],
    page: int = 0,
    emoji_service: DiscordEmojiService | None = None,
) -> None:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    if entries:
        current_page = _clamp_potion_page(page, len(entries))
        page_entries = _potion_page_entries(entries, current_page)
        owned_lines = [_potion_inventory_line(potion_service, entry, emoji_service) for entry in page_entries]
        page_count = _potion_page_count(len(entries))
        for index, chunk in enumerate(_chunk_lines(owned_lines), start=0):
            if page_count > 1 and index == 0:
                name = f"Owned Potions (Page {current_page + 1}/{page_count})"
            elif index == 0:
                name = "Owned Potions"
            else:
                name = "\u200b"
            response.add_field(name=name, value=chunk, inline=False)
    else:
        response.add_field(name="Owned Potions", value="None", inline=False)


def _build_dungeon_level_selector_embed(
    *,
    title: str,
    description: str,
    potion_service: PotionService,
    active: tuple[ActivePotion, ...],
    potion_entries: tuple[PotionInventoryEntry, ...],
    potion_page: int,
    banner_key: str,
) -> discord.Embed:
    selector = embed(title, description, colour=DEEP_NAVY)
    _add_active_potion_fields(selector, potion_service=potion_service, active=active)
    if len(active) < 3:
        _add_potion_inventory_fields(
            selector,
            potion_service=potion_service,
            entries=potion_entries,
            page=potion_page,
        )
    DEFAULT_DISCORD_ASSETS.apply_banner(selector, LOCATION_SERVICE.banner_asset_for(banner_key))
    return selector


def _add_active_potion_fields(
    response: discord.Embed,
    *,
    potion_service: PotionService,
    active: tuple[ActivePotion, ...],
    emoji_service: DiscordEmojiService | None = None,
) -> None:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    if active:
        active_lines = [
            (
                f"{_potion_marker(effect.item, emoji_service)} **{effect.item.name}** \n "
                f"{EM_SPACE}{EM_SPACE}{potion_service.effect_summary(effect.item)} - ends "
                f"{discord_relative_timestamp(effect.activation.effective_ends_at)}"
            )
            for effect in active
        ]
        response.add_field(name="Active Effects", value="\n".join(active_lines), inline=False)
        return
    response.add_field(name="Active Effects", value="None", inline=False)


def _potion_page_count(total_entries: int) -> int:
    if total_entries <= 0:
        return 1
    return ((total_entries - 1) // POTION_PAGE_SIZE) + 1


def _clamp_potion_page(page: int, total_entries: int) -> int:
    return max(0, min(page, _potion_page_count(total_entries) - 1))


def _potion_page_entries(
    entries: tuple[PotionInventoryEntry, ...],
    page: int,
) -> tuple[PotionInventoryEntry, ...]:
    current_page = _clamp_potion_page(page, len(entries))
    start = current_page * POTION_PAGE_SIZE
    return entries[start : start + POTION_PAGE_SIZE]


def _add_potion_page_buttons(
    view: discord.ui.View,
    *,
    potion_entries: tuple[PotionInventoryEntry, ...],
    page: int,
    row: int,
) -> None:
    if len(potion_entries) <= POTION_PAGE_SIZE:
        return
    view.add_item(
        PotionPageButton(
            emoji="⬅️",
            delta=-1,
            page=page,
            total_entries=len(potion_entries),
            row=row,
        )
    )
    view.add_item(
        PotionPageButton(
            emoji="➡️",
            delta=1,
            page=page,
            total_entries=len(potion_entries),
            row=row,
        )
    )


def _show_level_select_potion_controls(
    active: tuple[ActivePotion, ...],
    potion_entries: tuple[PotionInventoryEntry, ...],
) -> bool:
    return bool(potion_entries) and len(active) < 3


def _potion_thumbnail_asset(
    *,
    entries: tuple[PotionInventoryEntry, ...],
    active: tuple[ActivePotion, ...],
) -> str | None:
    for effect in active:
        asset_key = _potion_asset_key(effect.item)
        if asset_key:
            return asset_key
    for entry in entries:
        asset_key = _potion_asset_key(entry.item)
        if asset_key:
            return asset_key
    return None


def _potion_asset_key(item: PotionItem) -> str | None:
    if item.thumbnail_asset:
        return item.thumbnail_asset
    if item.effect_group in {"attack", "healing", "luck", "max_hp", "xp"}:
        return f"item.potion.{item.effect_group}.{item.tier:02d}"
    return None


def _potion_marker(item: PotionItem, emoji_service: DiscordEmojiService) -> str:
    return emoji_service.markdown_for(_potion_asset_key(item)) or POTION_TYPE_EMOJIS.get(item.effect_group, "🧪")


def _potion_inventory_line(
    potion_service: PotionService,
    entry: PotionInventoryEntry,
    emoji_service: DiscordEmojiService | None = None,
) -> str:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    emoji = _potion_marker(entry.item, emoji_service)
    return (
        f"{emoji} **{entry.item.name}** x{entry.stack.quantity} \n"
        f"{EM_SPACE}{EM_SPACE}{potion_service.effect_summary(entry.item)} - {human_duration(entry.item.duration_seconds, abr=True)}"
    )


def _potion_select_option(entry: PotionInventoryEntry, emoji_service: DiscordEmojiService) -> discord.SelectOption:
    custom_emoji = _potion_select_emoji(entry.item, emoji_service)
    return discord.SelectOption(
        label=_potion_option_label(entry, include_fallback_emoji=custom_emoji is None),
        value=entry.item.key,
        description=_potion_option_description(entry),
        emoji=custom_emoji,
    )


def _potion_select_emoji(item: PotionItem, emoji_service: DiscordEmojiService) -> discord.PartialEmoji | None:
    registry_entry = emoji_service.registry_entry_for(_potion_asset_key(item))
    if registry_entry is None:
        return None
    return discord.PartialEmoji(
        name=registry_entry.name,
        id=int(registry_entry.emoji_id),
        animated=registry_entry.animated,
    )


def _potion_option_label(entry: PotionInventoryEntry, *, include_fallback_emoji: bool = True) -> str:
    emoji = POTION_TYPE_EMOJIS.get(entry.item.effect_group, "🧪")
    prefix = f"{emoji} " if include_fallback_emoji else ""
    return _limit_component_text(f"{prefix}{entry.item.name} x{entry.stack.quantity}", 100)


def _potion_option_description(entry: PotionInventoryEntry) -> str:
    effect = PotionService().effect_summary(entry.item)
    return _limit_component_text(
        f"{effect} | {human_duration(entry.item.duration_seconds)}",
        100,
    )


def _chunk_lines(lines: list[str], *, limit: int = 1000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        line_length = len(line) + 1
        if current and current_length + line_length > limit:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += line_length
    if current:
        chunks.append("\n".join(current))
    return chunks


def _limit_component_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


class ShopView(DungeonActionView):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        defense_service: DefenseService,
        shop_service: ShopService,
        owner_user_id: int,
        is_defending: bool = False,
        stock: ShopStock,
        player: Player,
        selected_stock_number: int | None = None,
        emoji_service: DiscordEmojiService | None = None,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            exploration_service=exploration_service,
            defense_service=defense_service,
            shop_service=shop_service,
            owner_user_id=owner_user_id,
            is_defending=is_defending,
        )
        emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
        options = _shop_select_options(
            stock,
            player,
            shop_service,
            selected_stock_number=selected_stock_number,
            emoji_service=emoji_service,
        )
        if options:
            self.add_item(ShopPurchaseSelect(options))
        if selected_stock_number is not None:
            self.add_item(ShopBuySelectedButton(selected_stock_number))

    @discord.ui.button(label="Explore", style=discord.ButtonStyle.primary, row=1)
    async def explore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.start_exploration(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.success, row=1)
    async def defend(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if self.is_defending:
            await self.stop_defending(interaction)
            return
        await self.show_defense_selector(interaction)

    @discord.ui.button(label="Steward's Hall", style=discord.ButtonStyle.secondary, row=1)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self.show_hall(interaction)


class ShopPurchaseSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Browse Shop",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ShopView):
            await interaction.response.send_message("This shop is no longer available.", ephemeral=True)
            return
        await view.preview_shop_item(interaction, int(self.values[0]))


class ShopBuySelectedButton(discord.ui.Button):
    def __init__(self, stock_number: int) -> None:
        super().__init__(
            label="Buy Selected",
            style=discord.ButtonStyle.success,
            row=1,
            custom_id=f"shop:buy-selected:{stock_number}",
        )
        self.stock_number = stock_number

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ShopView):
            await interaction.response.send_message("This shop is no longer available.", ephemeral=True)
            return
        await view.buy_shop_item(interaction, self.stock_number)


def _shop_select_options(
    stock: ShopStock,
    player: Player,
    shop_service: ShopService,
    *,
    selected_stock_number: int | None = None,
    emoji_service: DiscordEmojiService | None = None,
) -> list[discord.SelectOption]:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    options: list[discord.SelectOption] = []
    owned_item_keys = _owned_equipment_keys(player)
    for index, item in enumerate(stock.items, start=1):
        if item.key in owned_item_keys:
            continue
        quote = shop_service.quote_stock_item(player, stock=stock, stock_number=index)
        options.append(
            discord.SelectOption(
                label=_shop_option_label(item),
                value=str(index),
                description=_shop_option_description(quote),
                emoji=equipment_emoji(item.slot, item.subtype),
                default=index == selected_stock_number,
            )
        )
    return options


def _owned_equipment_keys(player: Player) -> set[str]:
    return {
        item_key
        for slot in EQUIPMENT_SLOTS
        if (item_key := getattr(player, slot, None))
    }


def _shop_option_label(item: EquipmentItem) -> str:
    return _limit_component_text(item.name, 100)


def _shop_option_description(quote: ShopPurchaseQuote) -> str:
    rarity = rarity_badge_emoji(quote.item.rarity, custom=False)
    return _limit_component_text(
        (
            f"{rarity} {quote.item.slot.title()} | "
            f"{format_item_stats(quote.item)} | Price {gold_emoji(custom=False)} {quote.item.cost}"
        ),
        100,
    )


def _equipment_select_emoji(item: EquipmentItem, emoji_service: DiscordEmojiService) -> discord.PartialEmoji | None:
    registry_entry = emoji_service.registry_entry_for(item.thumbnail_asset)
    if registry_entry is None:
        return None
    return discord.PartialEmoji(
        name=registry_entry.name,
        id=int(registry_entry.emoji_id),
        animated=registry_entry.animated,
    )
