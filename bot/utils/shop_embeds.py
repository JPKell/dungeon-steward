from __future__ import annotations

import discord

from bot.models import Player
from bot.services.equipment_service import EquipmentItem, EquipmentService
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


def build_shop_embed(stock: ShopStock, *, player: Player, equipment: EquipmentService) -> discord.Embed:
    response = embed(
        "Dungeon Equipment Shop",
        (
            f"Combat Level {stock.combat_level} stock. "
            f"Refreshes today at {discord_timestamp(stock.refreshes_at, 't')}."
        ),
        colour=DEEP_NAVY,
    )
    response.add_field(name="Gold", value=str(player.gold))
    response.add_field(name="Equipped", value=_equipped_summary(player, equipment), inline=False)
    response.add_field(name="Stock", value=_stock_summary(stock), inline=False)
    response.timestamp = stock.refreshes_at
    response.set_footer(text="Buying an item equips it immediately and replaces the matching slot.")
    return response


def build_purchase_embed(purchase: PurchasedEquipment) -> discord.Embed:
    response = embed(
        "Equipment Purchased",
        (
            f"Equipped {purchase.item.name} in your {purchase.item.slot} slot. "
            f"Refreshes today at {discord_timestamp(purchase.stock.refreshes_at, 't')}."
        ),
        colour=WARM_GOLD,
    )
    cost_value = purchase.purchase_cost or purchase.item.cost
    response.add_field(name="Cost", value=f"{cost_value} gold")
    if purchase.trade_in_value > 0:
        response.add_field(name="Sell", value=f"{purchase.trade_in_value} gold")
    response.add_field(name="Remaining Gold", value=str(purchase.remaining_gold))
    response.add_field(name="Stats", value=format_item_stats(purchase.item))
    if purchase.item.description:
        response.add_field(name="Description", value=purchase.item.description, inline=False)
    if purchase.replaced_item is not None:
        response.add_field(name="Replaced", value=purchase.replaced_item.name, inline=False)
    response.timestamp = purchase.stock.refreshes_at
    response.set_footer(text="Shop refreshes")
    return response


def format_item_line(index: int, item: EquipmentItem) -> str:
    return (
        f"{index}. {item.name} | HP {item.hp} | ATK {item.attack} | DEF {item.defense} | SPD {item.speed}"
        f" — {item.cost} gold"
    )


def format_item_stats(item: EquipmentItem) -> str:
    return f"HP {item.hp} | ATK {item.attack} | DEF {item.defense} | SPD {item.speed}"


def rarity_badge(rarity: str) -> str:
    return RARITY_BADGES.get(rarity.lower(), "⚪")


def _stock_summary(stock: ShopStock) -> str:
    grouped: dict[str, list[EquipmentItem]] = {}
    for item in stock.items:
        grouped.setdefault(item.slot, []).append(item)

    lines: list[str] = []
    next_number = 1
    for slot in ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket"):
        items = grouped.get(slot)
        if not items:
            continue
        if lines:
            lines.append("")
        lines.append(f"**{SLOT_EMOJIS.get(slot, '📦')} {slot.title()}**")
        sorted_items = sorted(items, key=lambda entry: entry.cost)
        for item in sorted_items:
            lines.append(format_item_line(next_number, item))
            next_number += 1
    return "\n".join(lines)


def _equipped_summary(player: Player, equipment: EquipmentService) -> str:
    equipped = []
    for slot in ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket"):
        item = equipment.get_or_none(getattr(player, slot))
        if item is None:
            equipped.append(f"{SLOT_EMOJIS.get(slot, '📦')} empty")
            continue
        equipped.append(
            f"{SLOT_EMOJIS.get(slot, '📦')} {rarity_badge(item.rarity)} {item.name} | HP {item.hp} | ATK {item.attack} | DEF {item.defense} | SPD {item.speed} | Trade {max(0, int(item.cost * 0.1))} gold"
        )
    return "\n".join(equipped)
