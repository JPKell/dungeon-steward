from __future__ import annotations

import discord

from bot.models import Player
from bot.services.equipment_service import EquipmentItem, EquipmentService
from bot.services.shop_service import PurchasedEquipment, ShopStock
from bot.utils.embeds import DEEP_NAVY, WARM_GOLD, embed
from bot.utils.time import discord_relative_timestamp


def build_shop_embed(stock: ShopStock, *, player: Player, equipment: EquipmentService) -> discord.Embed:
    response = embed(
        "Dungeon Equipment Shop",
        (
            f"Combat Level {stock.combat_level} stock. "
            f"Refreshes {discord_relative_timestamp(stock.refreshes_at)}."
        ),
        colour=DEEP_NAVY,
    )
    response.add_field(name="Gold", value=str(player.gold))
    response.add_field(name="Equipped", value=_equipped_summary(player, equipment), inline=False)
    response.add_field(name="Stock", value=_stock_summary(stock), inline=False)
    response.set_footer(text="Buying an item equips it immediately and replaces the matching slot.")
    return response


def build_purchase_embed(purchase: PurchasedEquipment) -> discord.Embed:
    response = embed(
        "Equipment Purchased",
        f"Equipped {purchase.item.name} in your {purchase.item.slot} slot.",
        colour=WARM_GOLD,
    )
    response.add_field(name="Cost", value=f"{purchase.item.cost} gold")
    response.add_field(name="Remaining Gold", value=str(purchase.remaining_gold))
    response.add_field(name="Stats", value=format_item_stats(purchase.item))
    if purchase.replaced_item is not None:
        response.add_field(name="Replaced", value=purchase.replaced_item.name, inline=False)
    response.set_footer(text=f"Shop refreshes {discord_relative_timestamp(purchase.stock.refreshes_at)}")
    return response


def format_item_line(index: int, item: EquipmentItem) -> str:
    return (
        f"{index}. {item.name} [{item.rarity}] - {item.slot} - {item.cost} gold\n"
        f"   {format_item_stats(item)}"
    )


def format_item_stats(item: EquipmentItem) -> str:
    return f"HP +{item.hp} | ATK +{item.attack} | DEF +{item.defense} | SPD +{item.speed}"


def _stock_summary(stock: ShopStock) -> str:
    return "\n".join(format_item_line(index, item) for index, item in enumerate(stock.items, start=1))


def _equipped_summary(player: Player, equipment: EquipmentService) -> str:
    equipped = [
        f"{slot}: {_equipped_name(equipment, getattr(player, slot))}"
        for slot in ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket")
    ]
    return "\n".join(equipped)


def _equipped_name(equipment: EquipmentService, item_key: str | None) -> str:
    item = equipment.get_or_none(item_key)
    return item.name if item else "empty"
