from __future__ import annotations

from datetime import UTC, datetime

from bot.models import Player
from bot.services.equipment_service import EquipmentItem
from bot.services.shop_service import PurchasedEquipment, ShopStock
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
    stock_field = next(field for field in embed.fields if field.name == "Stock")
    gold_field = next(field for field in embed.fields if field.name == "🪙 250")

    assert "Heroic Blade" in equipped_field.value
    assert equipped_field.value.startswith("⚔️ HP 4")
    assert equipped_field.value.index("HP 4") < equipped_field.value.index("Heroic Blade")
    assert "HP 4" in equipped_field.value
    assert "ATK 8" in equipped_field.value
    assert "DEF 3" in equipped_field.value
    assert "SPD 2" in equipped_field.value
    assert "Trade 🪙 14" in equipped_field.value
    assert gold_field.value == "\u200b"
    assert "**⚔️ Weapon ⚔️**" in stock_field.value
    assert "1. HP 1 | ATK 3 | DEF 0 | SPD 1 | ⚪ Rusty Axe | 🪙 60" in stock_field.value
    assert "⚔️ 1." not in stock_field.value
    assert stock_field.value.index("Rusty Axe") < stock_field.value.index("Heroic Blade")
    assert "weapon" not in stock_field.value
    assert "gold" not in stock_field.value.lower()


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
