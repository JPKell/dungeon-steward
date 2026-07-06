from __future__ import annotations

import discord

from bot.models import Player
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService
from bot.services.equipment_service import EquipmentItem, EquipmentService
from bot.services.location_service import LOCATION_SERVICE
from bot.services.shop_service import PurchasedEquipment, ShopStock
from bot.utils.embeds import DEEP_NAVY, WARM_GOLD, embed
from bot.utils.time import discord_timestamp

RARITY_BADGES = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
}

SLOT_EMOJIS = {
    "weapon": "⚔️",
    "shield": "🛡️",
    "helm": "🪖",
    "armor": "🧥",
    "gloves": "🧤",
    "boots": "🥾",
    "trinket": "💍",
}

GOLD_EMOJI = "🪙"


def build_shop_embed(
    stock: ShopStock,
    *,
    player: Player,
    equipment: EquipmentService,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
) -> discord.Embed:
    response = embed(
        "Dungeon Equipment Shop",
        (
            f"Combat Level {stock.combat_level} stock. "
            f"Refreshes today at {discord_timestamp(stock.refreshes_at, 't')}."
        ),
        colour=DEEP_NAVY,
    )
    response.add_field(name=format_gold(player.gold), value="\u200b")
    response.add_field(name="Equipped", value=_equipped_summary(player, equipment), inline=False)
    response.add_field(name="Stock", value=_stock_summary(stock), inline=False)
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("equipment_shop"))
    asset_service.apply_thumbnail(response, _first_stock_thumbnail(stock))
    response.timestamp = stock.refreshes_at
    response.set_footer(text="Buying an item equips it immediately and replaces the matching slot.")
    return response


def build_purchase_embed(
    purchase: PurchasedEquipment,
    *,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
) -> discord.Embed:
    response = embed(
        "Equipment Purchased",
        (
            f"Equipped {purchase.item.name} in your {purchase.item.slot} slot. "
            f"Refreshes today at {discord_timestamp(purchase.stock.refreshes_at, 't')}."
        ),
        colour=WARM_GOLD,
    )
    cost_value = purchase.purchase_cost or purchase.item.cost
    response.add_field(name="Cost", value=format_gold(cost_value))
    if purchase.trade_in_value > 0:
        response.add_field(name="Trade", value=format_gold(purchase.trade_in_value))
    response.add_field(name="Remaining", value=format_gold(purchase.remaining_gold))
    response.add_field(name="Stats", value=format_item_stats(purchase.item))
    if purchase.item.description:
        response.add_field(name="Description", value=purchase.item.description, inline=False)
    if purchase.replaced_item is not None:
        response.add_field(name="Replaced", value=purchase.replaced_item.name, inline=False)
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("item_purchased"))
    asset_service.apply_thumbnail(response, purchase.item.thumbnail_asset)
    response.timestamp = purchase.stock.refreshes_at
    response.set_footer(text="Shop refreshes")
    return response


def format_item_line(index: int, item: EquipmentItem) -> str:
    return (
        f"{index}. {format_item_stats(item)} | {rarity_badge(item.rarity)} {item.name}"
        f" | {format_gold(item.cost)}"
    )


def format_item_stats(item: EquipmentItem) -> str:
    return f"HP {item.hp} | ATK {item.attack} | DEF {item.defense} | SPD {item.speed}"


def format_gold(amount: int) -> str:
    return f"{GOLD_EMOJI} {amount}"


def rarity_badge(rarity: str) -> str:
    return RARITY_BADGES.get(rarity.lower(), "⚪")


def _stock_summary(stock: ShopStock) -> str:
    lines: list[str] = []
    current_slot: str | None = None
    for index, item in enumerate(stock.items, start=1):
        if item.slot != current_slot:
            if lines:
                lines.append("")
            emoji = SLOT_EMOJIS.get(item.slot, "📦")
            lines.append(f"**{emoji} {item.slot.title()} {emoji}**")
            current_slot = item.slot
        lines.append(format_item_line(index, item))
    return "\n".join(lines)


def _equipped_summary(player: Player, equipment: EquipmentService) -> str:
    equipped = []
    for slot in ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket"):
        item = equipment.get_or_none(getattr(player, slot))
        if item is None:
            equipped.append(f"{SLOT_EMOJIS.get(slot, '📦')} empty")
            continue
        trade_value = max(0, int(item.cost * 0.1))
        equipped.append(
            f"{SLOT_EMOJIS.get(slot, '📦')} {format_item_stats(item)} | {rarity_badge(item.rarity)} {item.name}"
            f" | Trade {format_gold(trade_value)}"
        )
    return "\n".join(equipped)


def _first_stock_thumbnail(stock: ShopStock) -> str | None:
    for item in stock.items:
        if item.thumbnail_asset:
            return item.thumbnail_asset
    return None
