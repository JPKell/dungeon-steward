from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

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
    PotionInventoryStack,
    WeeklyPlayerContribution,
)
from bot.services.content_runtime import refresh_runtime_content_from_database
from bot.services.discord_emoji_service import DEFAULT_DISCORD_EMOJIS, DiscordEmojiService
from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService
from bot.services.energy_service import EnergyService
from bot.services.equipment_service import EQUIPMENT_SLOTS, CombatStats, EquipmentItem, EquipmentService
from bot.services.player_service import PlayerService
from bot.services.potion_service import EXPECTED_POTION_GROUPS, POTION_TYPE_EMOJIS, PotionItem, PotionService
from bot.services.progression_service import calculate_explore_level, grant_combat_xp, sync_combat_progression
from bot.utils.embeds import embed
from bot.utils.profile_embeds import build_profile_embed
from bot.utils.helpers import format_item_stats 
from bot.utils.emoji import equipment_emoji, rarity_badge_emoji
from bot.views.exploration import _build_potion_inventory_embed

log = logging.getLogger(__name__)

GrantCatalogKind = Literal["equipment", "potion"]
InspectPage = Literal["profile", "potions", "equipment"]

DIRECT_GRANT_CHOICES = (
    app_commands.Choice(name="Energy", value="energy"),
    app_commands.Choice(name="Gold", value="gold"),
    app_commands.Choice(name="Explore XP", value="explore_xp"),
    app_commands.Choice(name="Combat XP", value="combat_xp"),
    app_commands.Choice(name="Stat Points", value="stat_points"),
    app_commands.Choice(name="Current HP", value="current_hp"),
    app_commands.Choice(name="Max HP", value="max_hp"),
    app_commands.Choice(name="Attack", value="attack"),
    app_commands.Choice(name="Defense", value="defense"),
    app_commands.Choice(name="Speed", value="speed"),
    app_commands.Choice(name="Hero Influence", value="hero_influence"),
    app_commands.Choice(name="Villain Influence", value="villain_influence"),
    app_commands.Choice(name="Discoveries Found", value="discoveries_found"),
    app_commands.Choice(name="Defense Wins", value="defense_wins"),
    app_commands.Choice(name="Total Explorations", value="total_explorations"),
    app_commands.Choice(name="Successful Explorations", value="successful_explorations"),
    app_commands.Choice(name="Failed Explorations", value="failed_explorations"),
)

CATALOG_GRANT_CHOICES = (
    app_commands.Choice(name="Equipment Item", value="equipment"),
    app_commands.Choice(name="Potion", value="potion"),
)

GRANT_CHOICES = DIRECT_GRANT_CHOICES + CATALOG_GRANT_CHOICES
DIRECT_GRANT_LABELS = {choice.value: choice.name for choice in DIRECT_GRANT_CHOICES}
CATALOG_GRANT_LABELS = {choice.value: choice.name for choice in CATALOG_GRANT_CHOICES}
SLOT_ORDER = {slot: index for index, slot in enumerate(EQUIPMENT_SLOTS)}
POTION_GROUP_LABELS = {
    "xp": "Combat XP",
    "max_hp": "Max HP",
    "healing": "Healing",
    "attack": "Attack",
    "defense": "Defense",
    "luck": "Luck",
}
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024


@dataclass(frozen=True)
class GrantResult:
    title: str
    message: str


def _grant_direct_reward(player: Player, grant_key: str, amount: int, energy: EnergyService) -> GrantResult:
    if amount <= 0:
        raise ValueError("Grant amount must be positive")

    label = DIRECT_GRANT_LABELS.get(grant_key, grant_key.replace("_", " ").title())
    if grant_key == "energy":
        state = energy.grant(player, amount)
        return GrantResult("Grant Applied", f"Granted {amount} energy. Energy is now {state.energy}/{MAX_ENERGY}.")
    if grant_key == "gold":
        player.gold = max(0, int(player.gold or 0) + amount)
        return GrantResult("Grant Applied", f"Granted {amount} gold. Gold is now {player.gold}.")
    if grant_key == "explore_xp":
        before_level = max(1, int(player.explore_level or 1))
        player.experience = max(0, int(player.experience or 0) + amount)
        player.explore_level = max(before_level, calculate_explore_level(player.experience))
        gained = player.explore_level - before_level
        suffix = f" Explore level increased by {gained}." if gained else ""
        return GrantResult("Grant Applied", f"Granted {amount} Explore XP. Total Explore XP is {player.experience}.{suffix}")
    if grant_key == "combat_xp":
        levels, stat_points = grant_combat_xp(player, amount)
        suffix = ""
        if levels:
            suffix = f" Combat level increased by {levels}; stat points gained: {stat_points}."
        return GrantResult(
            "Grant Applied",
            f"Granted {amount} Combat XP. Combat XP is now {player.combat_xp}/{player.combat_xp_to_next_level}.{suffix}",
        )

    sync_combat_progression(player)
    if grant_key == "stat_points":
        player.unspent_stat_points = max(0, int(player.unspent_stat_points or 0) + amount)
        return GrantResult("Grant Applied", f"Granted {amount} stat points. Unspent stat points: {player.unspent_stat_points}.")
    if grant_key == "current_hp":
        player.current_hp = min(max(1, int(player.max_hp or 1)), max(1, int(player.current_hp or 1) + amount))
        return GrantResult("Grant Applied", f"Granted {amount} current HP. Current HP: {player.current_hp}/{player.max_hp}.")
    if grant_key == "max_hp":
        player.max_hp = max(1, int(player.max_hp or 1) + amount)
        player.current_hp = min(player.max_hp, max(1, int(player.current_hp or 1) + amount))
        return GrantResult("Grant Applied", f"Granted {amount} max HP. HP is now {player.current_hp}/{player.max_hp}.")

    if grant_key in {"attack", "defense", "speed"}:
        minimum = 0 if grant_key == "defense" else 1
        current = int(getattr(player, grant_key) or minimum)
        setattr(player, grant_key, max(minimum, current + amount))
        return GrantResult("Grant Applied", f"Granted {amount} {label}. {label}: {getattr(player, grant_key)}.")

    if grant_key in {
        "hero_influence",
        "villain_influence",
        "discoveries_found",
        "defense_wins",
        "total_explorations",
        "successful_explorations",
        "failed_explorations",
    }:
        current = int(getattr(player, grant_key) or 0)
        setattr(player, grant_key, max(0, current + amount))
        return GrantResult("Grant Applied", f"Granted {amount} {label}. {label}: {getattr(player, grant_key)}.")

    raise ValueError(f"Unsupported grant target: {grant_key}")


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

    @app_commands.command(name="grant", description="Grant resources, equipment, or potions to a player")
    @app_commands.describe(
        username="Player to receive the grant",
        item="What to grant",
        amount="Amount to grant. Equipment grants equip one selected item.",
    )
    @app_commands.choices(item=list(GRANT_CHOICES))
    async def grant(
        self,
        interaction: discord.Interaction,
        username: discord.Member,
        item: app_commands.Choice[str],
        amount: app_commands.Range[int, 1, 1_000_000] = 1,
    ) -> None:
        if not await self._guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        grant_key = item.value
        if grant_key in CATALOG_GRANT_LABELS:
            view = AdminGrantBrowserView(
                session_factory=self.session_factory,
                invoker_user_id=interaction.user.id,
                target_user_id=username.id,
                target_display_name=username.display_name,
                guild_id=interaction.guild_id,
                grant_kind=cast(GrantCatalogKind, grant_key),
                amount=int(amount),
                players=self.players,
                energy=self.energy,
            )
            await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
            return

        try:
            with self.session_factory() as db:
                player = db.scalar(
                    select(Player)
                    .where(
                        Player.guild_id == interaction.guild_id,
                        Player.discord_user_id == username.id,
                    )
                    .with_for_update()
                )
                if player is None:
                    player = self.players.get_or_create(
                        db,
                        guild_id=interaction.guild_id,
                        user_id=username.id,
                        display_name=username.display_name,
                    )
                result = _grant_direct_reward(player, grant_key, int(amount), self.energy)
                db.commit()
        except Exception:
            log.exception("Admin grant failed")
            await interaction.response.send_message("The grant ledger refused the entry. Please try again.", ephemeral=True)
            return

        response = embed(result.title, result.message)
        response.add_field(name="Target", value=username.display_name)
        response.add_field(name="Granted By", value=interaction.user.display_name)
        await interaction.response.send_message(embed=response, ephemeral=True)

    @app_commands.command(name="inspect", description="View a player's profile, potion inventory, and equipment")
    async def inspect(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not await self._guard(interaction):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        with self.session_factory() as db:
            player_exists = db.scalar(
                select(Player.id).where(
                    Player.guild_id == interaction.guild_id,
                    Player.discord_user_id == member.id,
                )
            )
        if player_exists is None:
            await interaction.response.send_message(f"No dungeon profile found for {member.display_name}.", ephemeral=True)
            return
        view = AdminPlayerInspectView(
            session_factory=self.session_factory,
            invoker_user_id=interaction.user.id,
            target_user_id=member.id,
            target_display_name=member.display_name,
            guild_id=interaction.guild_id,
            energy=self.energy,
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

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


class _AdminInspectAssetService:
    def apply_banner(self, _embed: discord.Embed, _asset_key: str | None) -> None:
        return None

    def apply_thumbnail(self, _embed: discord.Embed, _asset_key: str | None) -> None:
        return None


_ADMIN_INSPECT_ASSETS = _AdminInspectAssetService()


class AdminPlayerInspectView(discord.ui.View):
    PAGES: tuple[tuple[InspectPage, str], ...] = (
        ("profile", "Profile"),
        ("potions", "Potions"),
        ("equipment", "Equipment"),
    )

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        invoker_user_id: int,
        target_user_id: int,
        target_display_name: str,
        guild_id: int,
        energy: EnergyService,
        equipment: EquipmentService | None = None,
        potions: PotionService | None = None,
        emoji_service: DiscordEmojiService | None = None,
        page: InspectPage = "profile",
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.invoker_user_id = invoker_user_id
        self.target_user_id = target_user_id
        self.target_display_name = target_display_name
        self.guild_id = guild_id
        self.energy = energy
        self.equipment = equipment or EquipmentService()
        self.potions = potions or PotionService()
        self.emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
        self.page: InspectPage = page
        self._refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_user_id:
            return True
        await interaction.response.send_message("This inspect view belongs to another staff member.", ephemeral=True)
        return False

    def set_page(self, page: InspectPage) -> None:
        self.page = page
        self._refresh_components()

    def build_embed(self) -> discord.Embed:
        with self.session_factory() as db:
            player = self._player(db)
            if player is None:
                return embed("Player Not Found", f"No dungeon profile found for {self.target_display_name}.")
            if self.page == "profile":
                return self._build_profile_page(db, player)
            if self.page == "potions":
                return self._build_potions_page(db, player)
            return self._build_equipment_page(player)

    def _player(self, db) -> Player | None:
        return db.scalar(
            select(Player).where(
                Player.guild_id == self.guild_id,
                Player.discord_user_id == self.target_user_id,
            )
        )

    def _build_profile_page(self, db, player: Player) -> discord.Embed:
        state = self.energy.recalculate(player)
        sync_combat_progression(player)
        stats = _effective_combat_stats(player, self.equipment)
        response = build_profile_embed(
            display_name=self.target_display_name,
            player=player,
            energy_state=state,
            stats=stats,
            asset_service=_ADMIN_INSPECT_ASSETS,
        )
        response.set_footer(text="Admin inspect | Profile")
        db.commit()
        return response

    def _build_potions_page(self, db, player: Player) -> discord.Embed:
        active = self.potions.active_effects_at(db, player)
        entries = self.potions.inventory_entries(db, player)
        response = _build_potion_inventory_embed(
            potion_service=self.potions,
            entries=entries,
            active=active,
            asset_service=_ADMIN_INSPECT_ASSETS,
            emoji_service=self.emoji_service,
        )
        response.title = f"{self.target_display_name}'s Potion Inventory"
        response.set_footer(text="Admin inspect | Potions")
        return response

    def _build_equipment_page(self, player: Player) -> discord.Embed:
        response = embed(f"{self.target_display_name}'s Equipment")
        stats = _effective_combat_stats(player, self.equipment)
        bonuses = self.equipment.get_equipment_stat_bonuses(player)
        response.add_field(
            name="Effective Stats",
            value=_horizontal_stat_block(
                (
                    ("HP", f"{player.current_hp}/{stats.max_hp}"),
                    ("ATK", str(stats.attack)),
                    ("DEF", str(stats.defense)),
                    ("SPD", str(stats.speed)),
                )
            ),
            inline=False,
        )
        response.add_field(
            name="Equipment Bonuses",
            value=_horizontal_stat_block(
                (
                    ("HP", f"+{bonuses['max_hp']}"),
                    ("ATK", f"+{bonuses['attack']}"),
                    ("DEF", f"+{bonuses['defense']}"),
                    ("SPD", f"+{bonuses['speed']}"),
                )
            ),
            inline=False,
        )
        for slot in EQUIPMENT_SLOTS:
            item = self.equipment.get_or_none(getattr(player, slot), combat_level=player.combat_level)
            marker = equipment_emoji(item.slot, item.subtype) if item is not None else equipment_emoji(slot, "empty")
            rarity = f"{rarity_badge_emoji(item.rarity)} " if item is not None else ""
            response.add_field(
                name=f"{rarity}{marker} {_equipment_inspect_name(slot, item)}",
                value=_equipment_inspect_value(item, self.emoji_service),
                inline=False,
            )
        response.set_footer(text="Admin inspect | Equipment")
        return response

    def _refresh_components(self) -> None:
        self.clear_items()
        for page, label in self.PAGES:
            self.add_item(AdminInspectPageButton(page, label, disabled=page == self.page))


def _effective_combat_stats(player: Player, equipment: EquipmentService) -> CombatStats:
    bonuses = equipment.get_equipment_stat_bonuses(player)
    return CombatStats(
        max_hp=max(1, int(player.max_hp or 1) + bonuses["max_hp"]),
        attack=max(1, int(player.attack or 1) + bonuses["attack"]),
        defense=max(0, int(player.defense or 0) + bonuses["defense"]),
        speed=max(1, int(player.speed or 1) + bonuses["speed"]),
    )


def _horizontal_stat_block(values: tuple[tuple[str, str], ...]) -> str:
    widths = [max(len(label), len(value)) for label, value in values]
    header = "  ".join(label.ljust(width) for (label, _value), width in zip(values, widths, strict=True))
    row = "  ".join(value.ljust(width) for (_label, value), width in zip(values, widths, strict=True))
    return f"```text\n{header}\n{row}\n```"


def _equipment_inspect_value(item: EquipmentItem | None, emoji_service: DiscordEmojiService | None = None) -> str:
    if item is None:
        return "Empty"
    return "\n".join(
        (
            format_item_stats(item),
        )
    )


def _equipment_inspect_name(slot: str, item: EquipmentItem | None) -> str:
    if item is None:
        return f"Empty {slot.title()}"
    return item.name


class AdminInspectPageButton(discord.ui.Button):
    def __init__(self, page: InspectPage, label: str, *, disabled: bool = False) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary, disabled=disabled, row=0)
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AdminPlayerInspectView):
            await interaction.response.send_message("This inspect view is no longer available.", ephemeral=True)
            return
        view.set_page(self.page)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class AdminGrantBrowserView(discord.ui.View):
    PAGE_SIZE = 10

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        invoker_user_id: int,
        target_user_id: int,
        target_display_name: str,
        guild_id: int,
        grant_kind: GrantCatalogKind,
        amount: int,
        players: PlayerService,
        energy: EnergyService,
        equipment: EquipmentService | None = None,
        potions: PotionService | None = None,
        emoji_service: DiscordEmojiService | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.invoker_user_id = invoker_user_id
        self.target_user_id = target_user_id
        self.target_display_name = target_display_name
        self.guild_id = guild_id
        self.grant_kind = grant_kind
        self.amount = max(1, int(amount))
        self.players = players
        self.energy = energy
        self.equipment = equipment or EquipmentService()
        self.potions = potions or PotionService()
        self.emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
        self.category = "all"
        self.page = 0
        self._refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_user_id:
            return True
        await interaction.response.send_message("This grant picker belongs to another staff member.", ephemeral=True)
        return False

    def build_embed(self) -> discord.Embed:
        title = f"Grant {CATALOG_GRANT_LABELS[self.grant_kind]}"
        response = embed(title, "Choose a category, page through the list, then select what to grant.")
        response.add_field(name="Target", value=self.target_display_name)
        amount_value = "equips one selected item" if self.grant_kind == "equipment" else str(self.amount)
        response.add_field(name="Amount", value=amount_value)
        response.add_field(name="Category", value=self._category_label(self.category))

        page_items = self._page_items()
        if page_items:
            lines = [self._line_for(index, item) for index, item in enumerate(page_items, start=self._page_start() + 1)]
            _add_limited_line_fields(
                response,
                name=f"Page {self.page + 1}/{self._page_count()}",
                lines=lines,
                inline=False,
            )
        else:
            response.add_field(name="Page", value="No matching entries.", inline=False)
        return response

    def set_category(self, category: str) -> None:
        valid = {value for value, _label in self._categories()}
        self.category = category if category in valid else "all"
        self.page = 0
        self._refresh_components()

    def move_page(self, delta: int) -> None:
        self.page = min(max(0, self.page + delta), self._page_count() - 1)
        self._refresh_components()

    async def grant_selected(self, interaction: discord.Interaction, item_key: str) -> None:
        try:
            if self.grant_kind == "equipment":
                result = self._grant_equipment(item_key)
            else:
                result = self._grant_potion(item_key)
        except Exception:
            log.exception("Admin catalog grant failed")
            await interaction.response.edit_message(
                embed=embed("Grant Failed", "The grant ledger refused the selected entry."),
                view=None,
            )
            return

        response = embed(result.title, result.message)
        response.add_field(name="Target", value=self.target_display_name)
        await interaction.response.edit_message(embed=response, view=None)
        self.stop()

    def _grant_equipment(self, equipment_key: str) -> GrantResult:
        item = self.equipment.get(equipment_key)
        with self.session_factory() as db:
            player = db.scalar(
                select(Player)
                .where(
                    Player.guild_id == self.guild_id,
                    Player.discord_user_id == self.target_user_id,
                )
                .with_for_update()
            )
            if player is None:
                player = self.players.get_or_create(
                    db,
                    guild_id=self.guild_id,
                    user_id=self.target_user_id,
                    display_name=self.target_display_name,
                )
            replaced = self.equipment.get_or_none(getattr(player, item.slot), combat_level=player.combat_level)
            setattr(player, item.slot, item.key)
            db.commit()
        replaced_text = f" Replaced {replaced.name}." if replaced is not None else ""
        return GrantResult("Equipment Granted", f"Equipped {item.name} in the {item.slot} slot.{replaced_text}")

    def _grant_potion(self, item_key: str) -> GrantResult:
        item = self.potions.content.get(item_key)
        with self.session_factory() as db:
            player = db.scalar(
                select(Player)
                .where(
                    Player.guild_id == self.guild_id,
                    Player.discord_user_id == self.target_user_id,
                )
                .with_for_update()
            )
            if player is None:
                player = self.players.get_or_create(
                    db,
                    guild_id=self.guild_id,
                    user_id=self.target_user_id,
                    display_name=self.target_display_name,
                )
            before = self._current_potion_quantity(db, player.id, item.key)
            stack = self.potions.add_drop(db, player, item.key, amount=self.amount)
            added = max(0, int(stack.quantity or 0) - before)
            db.commit()
        cap_note = " Stack is already at its cap." if added < self.amount else ""
        return GrantResult(
            "Potion Granted",
            f"Added {added} x {item.name}. Stack quantity is now {before + added}.{cap_note}",
        )

    def _current_potion_quantity(self, db, player_id: int, item_key: str) -> int:
        stack = db.scalar(
            select(PotionInventoryStack).where(
                PotionInventoryStack.player_id == player_id,
                PotionInventoryStack.item_key == item_key,
            )
        )
        return 0 if stack is None else max(0, int(stack.quantity or 0))

    def _refresh_components(self) -> None:
        self.clear_items()
        self.add_item(AdminGrantCategorySelect(self))
        self.add_item(AdminGrantItemSelect(self))
        self.add_item(AdminGrantPageButton(self, direction=-1))
        self.add_item(AdminGrantPageButton(self, direction=1))

    def _categories(self) -> tuple[tuple[str, str], ...]:
        if self.grant_kind == "equipment":
            return (("all", "All equipment"),) + tuple((slot, slot.title()) for slot in EQUIPMENT_SLOTS)
        return (("all", "All potions"),) + tuple((group, POTION_GROUP_LABELS[group]) for group in EXPECTED_POTION_GROUPS)

    def _category_label(self, category: str) -> str:
        return dict(self._categories()).get(category, "All")

    def _all_items(self) -> list[EquipmentItem | PotionItem]:
        if self.grant_kind == "equipment":
            items = [item for item in self.equipment.items if self.category == "all" or item.slot == self.category]
            return sorted(
                items,
                key=lambda item: (SLOT_ORDER.get(item.slot, 999), item.min_level, item.rarity, item.name),
            )
        items = [
            item
            for item in self.potions.content.items
            if item.enabled and (self.category == "all" or item.effect_group == self.category)
        ]
        return sorted(items, key=lambda item: (item.sort_order, item.name))

    def _page_start(self) -> int:
        return self.page * self.PAGE_SIZE

    def _page_items(self) -> list[EquipmentItem | PotionItem]:
        items = self._all_items()
        start = self._page_start()
        return items[start : start + self.PAGE_SIZE]

    def _page_count(self) -> int:
        return max(1, (len(self._all_items()) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    def _line_for(self, index: int, item: EquipmentItem | PotionItem) -> str:
        if isinstance(item, EquipmentItem):
            return (
                f"{index}. {rarity_badge_emoji(item.rarity)} {item.name} | {item.slot} | "
                f"L{item.min_level}-{item.max_level} | {format_item_stats(item)}"
            )
        emoji = _potion_emoji_markdown(item, self.emoji_service) or POTION_TYPE_EMOJIS.get(item.effect_group, "")
        return f"{index}. {emoji} {item.name} | T{item.tier} {item.rarity} | {self.potions.effect_summary(item)}"

    def option_for(self, item: EquipmentItem | PotionItem) -> discord.SelectOption:
        if isinstance(item, EquipmentItem):
            return discord.SelectOption(
                label=_limit_component_text(item.name, 100),
                value=item.key,
                description=_limit_component_text(
                    f"{item.slot} | {item.rarity} | L{item.min_level}-{item.max_level} | {format_item_stats(item)}",
                    100,
                ),
            )
        emoji = _potion_select_emoji(item, self.emoji_service) or POTION_TYPE_EMOJIS.get(item.effect_group)
        return discord.SelectOption(
            label=_limit_component_text(item.name, 100),
            value=item.key,
            description=_limit_component_text(
                f"T{item.tier} {item.rarity} | {self.potions.effect_summary(item)}",
                100,
            ),
            emoji=emoji,
        )


def _potion_asset_key(item: PotionItem) -> str | None:
    if item.thumbnail_asset:
        return item.thumbnail_asset
    if item.effect_group in {"attack", "healing", "luck", "max_hp", "xp"}:
        return f"item.potion.{item.effect_group}.{item.tier:02d}"
    return None


def _potion_emoji_markdown(item: PotionItem, emoji_service: DiscordEmojiService) -> str | None:
    return emoji_service.markdown_for(_potion_asset_key(item))


def _potion_select_emoji(item: PotionItem, emoji_service: DiscordEmojiService) -> discord.PartialEmoji | None:
    registry_entry = emoji_service.registry_entry_for(_potion_asset_key(item))
    if registry_entry is None:
        return None
    return discord.PartialEmoji(
        name=registry_entry.name,
        id=int(registry_entry.emoji_id),
        animated=registry_entry.animated,
    )


def _add_limited_line_fields(
    response: discord.Embed,
    *,
    name: str,
    lines: list[str],
    inline: bool,
) -> None:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        safe_line = _limit_component_text(line, DISCORD_EMBED_FIELD_VALUE_LIMIT)
        separator_length = 1 if current else 0
        if current and current_length + separator_length + len(safe_line) > DISCORD_EMBED_FIELD_VALUE_LIMIT:
            chunks.append("\n".join(current))
            current = [safe_line]
            current_length = len(safe_line)
            continue
        current.append(safe_line)
        current_length += separator_length + len(safe_line)
    if current:
        chunks.append("\n".join(current))

    for index, chunk in enumerate(chunks):
        field_name = name if index == 0 else f"{name} (continued)"
        response.add_field(name=field_name, value=chunk, inline=inline)


class AdminGrantCategorySelect(discord.ui.Select):
    def __init__(self, grant_view: AdminGrantBrowserView) -> None:
        options = [
            discord.SelectOption(label=label, value=value, default=value == grant_view.category)
            for value, label in grant_view._categories()
        ]
        super().__init__(placeholder="Filter category", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AdminGrantBrowserView):
            await interaction.response.send_message("This grant picker is no longer available.", ephemeral=True)
            return
        view.set_category(self.values[0])
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class AdminGrantItemSelect(discord.ui.Select):
    def __init__(self, grant_view: AdminGrantBrowserView) -> None:
        items = grant_view._page_items()
        if items:
            options = [grant_view.option_for(item) for item in items]
            disabled = False
            placeholder = "Select item to grant"
        else:
            options = [discord.SelectOption(label="No matching entries", value="none")]
            disabled = True
            placeholder = "No entries"
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            disabled=disabled,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AdminGrantBrowserView):
            await interaction.response.send_message("This grant picker is no longer available.", ephemeral=True)
            return
        await view.grant_selected(interaction, self.values[0])


class AdminGrantPageButton(discord.ui.Button):
    def __init__(self, grant_view: AdminGrantBrowserView, *, direction: int) -> None:
        self.direction = direction
        label = "Previous" if direction < 0 else "Next"
        disabled = grant_view.page <= 0 if direction < 0 else grant_view.page >= grant_view._page_count() - 1
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AdminGrantBrowserView):
            await interaction.response.send_message("This grant picker is no longer available.", ephemeral=True)
            return
        view.move_page(self.direction)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


def _limit_component_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."
