from __future__ import annotations

from datetime import UTC, datetime

from bot.models import Player
from bot.services.equipment_service import EquipmentItem
from bot.services.shop_service import PurchasedEquipment, ShopPurchaseQuote, ShopStock
from bot.utils.shop_embeds import build_purchase_embed, build_shop_embed


class StubEquipmentService:
    def __init__(self, item: EquipmentItem) -> None:
        self.item = item

    def get_or_none(self, key: str | None) -> EquipmentItem | None:
        if key == self.item.key:
            return self.item
        return None


def test_shop_embed_shows_equipped_stats_and_rarity_badges() -> None:
    item = EquipmentItem(
        key="heroic-blade",
        name="Heroic Blade",
        slot="weapon",
        rarity="legendary",
        min_level=1,
        max_level=10,
        cost=140,
        hp=4,
        attack=8,
        defense=3,
        speed=2,
    )
    cheaper_item = EquipmentItem(
        key="rusty-axe",
        name="Rusty Axe",
        slot="weapon",
        rarity="common",
        min_level=1,
        max_level=10,
        cost=60,
        hp=1,
        attack=3,
        defense=0,
        speed=1,
    )
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Test Player",
        gold=250,
        weapon=item.key,
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(cheaper_item, item),
    )

    embed = build_shop_embed(stock, player=player, equipment=StubEquipmentService(item))

    equipped_field = next(field for field in embed.fields if field.name == "Equipped")

    assert embed.title == "Dungeon Equipment Shop                    🪙 250"
    assert embed.description is None
    assert "Heroic Blade" in equipped_field.value
    assert equipped_field.value.startswith("⚔️ Heroic Blade 🟡")
    assert equipped_field.value.index("Heroic Blade") < equipped_field.value.index("HP 4")
    assert "HP 4" in equipped_field.value
    assert "ATK 8" in equipped_field.value
    assert "DEF 3" in equipped_field.value
    assert "SPD 2" in equipped_field.value
    assert "Trade-in 🪙 14" in equipped_field.value
    assert "🛡️ Empty" in equipped_field.value
    assert "No item equipped" not in equipped_field.value
    assert embed.timestamp is None
    assert embed.footer.text is not None
    footer_lines = embed.footer.text.splitlines()
    assert footer_lines[0] == "Buying an item equips it immediately and replaces the matching slot."
    assert footer_lines[1] == "Items you already own are hidden in shop."
    assert footer_lines[2].startswith("Combat Level 5 stock. Refreshes today at ")
    assert "<t:" not in footer_lines[2]
    assert all(field.name != "Stock" for field in embed.fields)
    assert "Rusty Axe" not in "\n".join(field.value for field in embed.fields)


def test_shop_embed_selected_purchase_shows_net_trade_in_price() -> None:
    item = EquipmentItem(
        key="heroic-blade",
        name="Heroic Blade",
        slot="weapon",
        rarity="legendary",
        min_level=1,
        max_level=10,
        cost=140,
        hp=4,
        attack=8,
        defense=3,
        speed=2,
    )
    replaced_item = EquipmentItem(
        key="rusty-knife",
        name="Rusty Knife",
        slot="weapon",
        rarity="common",
        min_level=1,
        max_level=10,
        cost=50,
        hp=1,
        attack=1,
        defense=0,
        speed=0,
    )
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Test Player",
        gold=250,
        weapon=replaced_item.key,
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(item,),
    )
    quote = ShopPurchaseQuote(
        item=item,
        replaced_item=replaced_item,
        stock=stock,
        trade_in_value=5,
        purchase_cost=135,
    )

    embed = build_shop_embed(stock, player=player, equipment=StubEquipmentService(replaced_item), selected_quote=quote)

    selected_field = next(field for field in embed.fields if field.name.endswith("Selected Purchase"))
    lines = selected_field.value.splitlines()

    assert lines[0] == "⚔️ Heroic Blade 🟡"
    assert lines[1] == "HP 4 | ATK 8 | DEF 3 | SPD 2"
    assert lines[2] == "Purchase Price After Trade-in 🪙 135"
    assert "Purchase Price After Trade-in 🪙 135" in selected_field.value
    assert "Sticker" not in selected_field.value
    assert "Trade-in -" not in selected_field.value
    assert "After Purchase" not in selected_field.value


def test_purchase_embed_uses_embed_timestamp_for_refreshes() -> None:
    item = EquipmentItem(
        key="heroic-blade",
        name="Heroic Blade",
        slot="weapon",
        rarity="legendary",
        min_level=1,
        max_level=10,
        cost=140,
        hp=4,
        attack=8,
        defense=3,
        speed=2,
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(item,),
    )
    purchase = PurchasedEquipment(item=item, replaced_item=None, remaining_gold=100, stock=stock)

    embed = build_purchase_embed(purchase)

    assert embed.timestamp == stock.refreshes_at
    assert embed.description is not None
    assert "Refreshes today at" in embed.description
    assert "<t:" in embed.description
    assert embed.footer.text == "Shop refreshes"


def test_purchase_embed_shows_trade_in_discount() -> None:
    item = EquipmentItem(
        key="heroic-blade",
        name="Heroic Blade",
        slot="weapon",
        rarity="legendary",
        min_level=1,
        max_level=10,
        cost=140,
        hp=4,
        attack=8,
        defense=3,
        speed=2,
    )
    replaced_item = EquipmentItem(
        key="rusty-knife",
        name="Rusty Knife",
        slot="weapon",
        rarity="common",
        min_level=1,
        max_level=10,
        cost=50,
        hp=1,
        attack=1,
        defense=0,
        speed=0,
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(item,),
    )
    purchase = PurchasedEquipment(
        item=item,
        replaced_item=replaced_item,
        remaining_gold=86,
        stock=stock,
        trade_in_value=14,
        purchase_cost=126,
    )

    embed = build_purchase_embed(purchase)

    trade_in_field = next(field for field in embed.fields if field.name == "Trade")
    cost_field = next(field for field in embed.fields if field.name == "Cost")

    assert trade_in_field.value == "🪙 14"
    assert cost_field.value == "🪙 126"
