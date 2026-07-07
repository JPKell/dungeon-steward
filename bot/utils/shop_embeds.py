from __future__ import annotations

import discord

from bot.models import Player
from bot.services.discord_asset_service import DEFAULT_DISCORD_ASSETS, DiscordAssetService
from bot.services.discord_emoji_service import DEFAULT_DISCORD_EMOJIS, DiscordEmojiService
from bot.services.equipment_service import EquipmentItem, EquipmentService
from bot.services.location_service import LOCATION_SERVICE
from bot.services.shop_service import PurchasedEquipment, ShopPurchaseQuote, ShopStock
from bot.utils.embeds import DEEP_NAVY, WARM_GOLD, embed
from bot.utils.time import discord_timestamp, local_clock_time

RARITY_BADGES = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
}

RARITY_EMOJI_ASSETS = {
    "common": "equipment.common",
    "uncommon": "equipment.uncommon",
    "rare": "equipment.rare",
    "epic": "equipment.epic",
    "legendary": "equipment.legendary",
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
GOLD_EMOJI_ASSET = "misc.gold"
GOLD_THUMBNAIL_ASSET = "misc.gold"

EMPTY_EQUIPMENT_EMOJI_ASSETS = {
    "weapon": "equipment.weapon_blade",
    "shield": "equipment.shield_ward",
    "helm": "equipment.helm_helm",
    "armor": "equipment.armor_cuirass",
    "gloves": "equipment.gloves_gauntlets",
    "boots": "equipment.boots_greaves",
    "trinket": "equipment.trinket_token",
}


def build_shop_embed(
    stock: ShopStock,
    *,
    player: Player,
    equipment: EquipmentService,
    selected_quote: ShopPurchaseQuote | None = None,
    asset_service: DiscordAssetService = DEFAULT_DISCORD_ASSETS,
    emoji_service: DiscordEmojiService | None = None,
) -> discord.Embed:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    response = embed(
        _shop_title(player, emoji_service),
        colour=DEEP_NAVY,
    )
    response.add_field(name="Equipped", value=_equipped_summary(player, equipment, emoji_service), inline=False)
    if selected_quote is not None:
        response.add_field(
            name="____________\nSelected Purchase",
            value=_selected_purchase_summary(selected_quote, player, emoji_service),
            inline=False,
        )
    asset_service.apply_banner(response, LOCATION_SERVICE.banner_asset_for("equipment_shop"))
    thumbnail_asset = selected_quote.item.thumbnail_asset if selected_quote is not None else GOLD_THUMBNAIL_ASSET
    asset_service.apply_thumbnail(response, thumbnail_asset)
    response.set_footer(
        text=(
            "Buying an item equips it immediately and replaces the matching slot.\n"
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
        ),
        colour=WARM_GOLD,
    )
    cost_value = purchase.purchase_cost or purchase.item.cost
    response.add_field(name="Cost", value=format_gold(cost_value))
    if purchase.trade_in_value > 0:
        response.add_field(name="Trade", value=format_gold(purchase.trade_in_value))
    response.add_field(name="Remaining", value=format_gold(purchase.remaining_gold))
    response.add_field(name="Stats", value=format_purchase_item_stats(purchase.item), inline=False)
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


def format_purchase_item_stats(item: EquipmentItem) -> str:
    return f"HP | ATK | DEF | SPD\n{item.hp} | {item.attack} | {item.defense} | {item.speed}"


def format_gold(amount: int, emoji_service: DiscordEmojiService | None = None) -> str:
    return f"{gold_marker(emoji_service)} {amount}"


def _shop_title(player: Player, emoji_service: DiscordEmojiService | None = None) -> str:
    return f"Dungeon Equipment Shop                    {format_gold(player.gold, emoji_service)}"


def rarity_badge(rarity: str, emoji_service: DiscordEmojiService | None = None) -> str:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    normalized = rarity.lower()
    return emoji_service.markdown_for(RARITY_EMOJI_ASSETS.get(normalized)) or RARITY_BADGES.get(normalized, "⚪")


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


def _equipped_summary(player: Player, equipment: EquipmentService, emoji_service: DiscordEmojiService) -> str:
    equipped = []
    for slot in ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket"):
        item = equipment.get_or_none(getattr(player, slot))
        if item is None:
            emoji = empty_equipment_marker(slot, emoji_service)
            equipped.append(f"{emoji} Empty")
            continue
        emoji = equipment_marker(item, emoji_service)
        rarity = rarity_badge(item.rarity, emoji_service)
        trade_value = int(item.cost * 0.1)
        equipped.append(
            f"{rarity} {emoji} {item.name}\n"
            f"{format_item_stats(item)} | Trade-in {format_gold(trade_value, emoji_service)}"
        )
    return "\n\n".join(equipped)


def _selected_purchase_summary(quote: ShopPurchaseQuote, player: Player, emoji_service: DiscordEmojiService) -> str:
    lines = [
        (
            f"{rarity_badge(quote.item.rarity, emoji_service)} "
            f"{equipment_marker(quote.item, emoji_service)} {quote.item.name}"
        ),
        format_item_stats(quote.item),
        f"Purchase Price After Trade-in {format_gold(quote.purchase_cost, emoji_service)}",
    ]
    if player.gold < quote.purchase_cost:
        lines.append(f"Short {format_gold(quote.purchase_cost - player.gold, emoji_service)}")
    return "\n".join(lines)


def _first_stock_thumbnail(stock: ShopStock) -> str | None:
    for item in stock.items:
        if item.thumbnail_asset:
            return item.thumbnail_asset
    return None


def equipment_marker(item: EquipmentItem, emoji_service: DiscordEmojiService | None = None) -> str:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    return emoji_service.markdown_for(item.thumbnail_asset) or SLOT_EMOJIS.get(item.slot, "📦")


def empty_equipment_marker(slot: str, emoji_service: DiscordEmojiService | None = None) -> str:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    return emoji_service.markdown_for(EMPTY_EQUIPMENT_EMOJI_ASSETS.get(slot)) or SLOT_EMOJIS.get(slot, "📦")


def gold_marker(emoji_service: DiscordEmojiService | None = None) -> str:
    emoji_service = emoji_service or DEFAULT_DISCORD_EMOJIS
    return emoji_service.markdown_for(GOLD_EMOJI_ASSET) or GOLD_EMOJI
