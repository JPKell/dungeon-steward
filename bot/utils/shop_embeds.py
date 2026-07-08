from __future__ import annotations

import discord

from bot.models import Player
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService
from bot.services.equipment_service import EquipmentItem, EquipmentService
from bot.services.location_service import LOCATION_SERVICE
from bot.services.shop_service import PurchasedEquipment, ShopPurchaseQuote, ShopStock
from bot.utils.embeds import DEEP_NAVY, WARM_GOLD, embed
from bot.utils.time import discord_timestamp, local_clock_time
from bot.utils.emoji import rarity_badge_emoji, equipment_emoji
from bot.utils.helpers import format_gold, format_item_stats


DISCORD_FIELD_VALUE_LIMIT = 1024


def build_shop_embed(
    stock: ShopStock,
    *,
    player: Player,
    equipment: EquipmentService,
    selected_quote: ShopPurchaseQuote | None = None,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
) -> discord.Embed:
    ''' Build a Discord embed for the equipment shop that shows the 
        player's equipped items and items available for purchase. 
        This does not include the shop items themselves, which are handled separately. '''

    response = embed(
        _shop_title(player),
        colour=DEEP_NAVY,
    )
    for index, value in enumerate(_equipped_summary_fields(player, equipment)):
        response.add_field(name="Equipped" if index == 0 else "Equipped Continued", value=value, inline=False)
    if selected_quote is not None:
        response.add_field(
            name="____________\nSelected Purchase",
            value=_selected_purchase_summary(selected_quote, player),
            inline=False,
        )
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("equipment_shop"))
    thumbnail_asset = selected_quote.item.thumbnail_asset if selected_quote is not None else "misc.gold"
    asset_service.apply_thumbnail(response, thumbnail_asset)
    response.set_footer(
        text=(
            "Buying an item equips it immediately and sells the matching slot.\n"
            "Items you already own are hidden in shop.\n"
            f"Combat Level {stock.combat_level} stock. Refreshes today at {local_clock_time(stock.refreshes_at)}."
        )
    )
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
    response.add_field(name="Stats", value=format_item_stats(purchase.item), inline=False)
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
        f"{index}. {format_item_stats(item)} | {rarity_badge_emoji(item.rarity)} {item.name}"
        f" | {format_gold(item.cost)}"
    )



def format_purchase_item_stats(item: EquipmentItem) -> str:
    return f"HP | ATK | DEF | SPD\n{item.hp} | {item.attack} | {item.defense} | {item.speed}"


def _shop_title(player: Player) -> str:
    return f"Dungeon Equipment Shop                    {format_gold(player.gold)}"


def _equipped_summary_fields(player: Player, equipment: EquipmentService) -> list[str]:
    fields: list[str] = []
    current = ""
    for slot in ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket"):
        item = equipment.get_or_none(getattr(player, slot))
        if item is None:
            emoji = equipment_emoji(slot, "empty")
            block = f"{emoji} Empty"
        else:
            emoji = equipment_emoji(item.slot, item.subtype)
            rarity = rarity_badge_emoji(item.rarity)
            trade_value = int(item.cost * 0.1)
            block = (
                f"{rarity} {emoji} {item.name}\n"
                f"{format_item_stats(item)} | Trade-in {format_gold(trade_value)}"
            )
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) > DISCORD_FIELD_VALUE_LIMIT and current:
            fields.append(current)
            current = block
        else:
            current = candidate
    if current:
        fields.append(current)
    return fields


def _selected_purchase_summary(quote: ShopPurchaseQuote, player: Player) -> str:
    lines = [
        (
            f"{rarity_badge_emoji(quote.item.rarity)} "
            f"{equipment_emoji(quote.item.slot, quote.item.subtype)} {quote.item.name}"
        ),
        format_item_stats(quote.item),
        f"Purchase Price After Trade-in {format_gold(quote.purchase_cost)}",
    ]
    if player.gold < quote.purchase_cost:
        lines.append(f"Short {format_gold(quote.purchase_cost - player.gold)}")
    return "\n".join(lines)


