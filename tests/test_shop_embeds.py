from __future__ import annotations

from datetime import UTC, datetime

from bot.models import Player
from bot.services.discord_asset_service import DiscordAssetService
from bot.services.discord_emoji_service import DiscordEmojiService, EmojiCatalog, EmojiDefinition, EmojiRegistry, EmojiRegistryEntry
from bot.services.equipment_service import EquipmentItem
from bot.services.shop_service import PurchasedEquipment, ShopPurchaseQuote, ShopStock
from bot.utils.shop_embeds import build_purchase_embed, build_shop_embed


class StubEquipmentService:
    def __init__(self, *items: EquipmentItem) -> None:
        self.items = {item.key: item for item in items}

    def get_or_none(self, key: str | None) -> EquipmentItem | None:
        return self.items.get(key)


def _equipment_emoji_service(tmp_path) -> DiscordEmojiService:
    keys = {
        "equipment.weapon_blade": ("ds_eq_weapon_blade", "111111111"),
        "equipment.shield_ward": ("ds_eq_shield_ward", "222222222"),
        "equipment.helm_helm": ("ds_eq_helm_helm", "333333333"),
        "equipment.armor_cuirass": ("ds_eq_armor_cuirass", "444444444"),
        "equipment.gloves_gauntlets": ("ds_eq_gloves_gauntlets", "777777777"),
        "equipment.boots_greaves": ("ds_eq_boots_greaves", "555555555"),
        "equipment.trinket_token": ("ds_eq_trinket_token", "666666666"),
        "equipment.common": ("ds_e_common", "888888881"),
        "equipment.legendary": ("ds_e_legendary", "888888885"),
        "misc.gold": ("ds_m_gold", "999999999"),
    }
    return DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                key: EmojiDefinition(
                    key=key,
                    name=name,
                    path=tmp_path / f"{name}.png",
                    alt_text=name,
                )
                for key, (name, _emoji_id) in keys.items()
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                key: EmojiRegistryEntry(
                    key=key,
                    name=name,
                    emoji_id=emoji_id,
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
                for key, (name, emoji_id) in keys.items()
            },
        ),
    )


def test_shop_embed_shows_equipped_stats_and_rarity_badges(tmp_path) -> None:
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

    embed = build_shop_embed(
        stock,
        player=player,
        equipment=StubEquipmentService(item),
        emoji_service=_equipment_emoji_service(tmp_path),
        asset_service=DiscordAssetService(allow_local_fallback=True),
    )

    equipped_field = next(field for field in embed.fields if field.name == "Equipped")

    assert embed.title == "Dungeon Equipment Shop                    <:ds_m_gold:999999999> 250"
    assert embed.description is None
    assert "Heroic Blade" in equipped_field.value
    assert equipped_field.value.startswith("<:ds_e_legendary:888888885> ⚔️ Heroic Blade")
    assert equipped_field.value.index("Heroic Blade") < equipped_field.value.index("HP 4")
    assert "HP 4" in equipped_field.value
    assert "ATK 8" in equipped_field.value
    assert "DEF 3" in equipped_field.value
    assert "SPD 2" in equipped_field.value
    assert "Trade-in <:ds_m_gold:999999999> 14" in equipped_field.value
    assert embed.thumbnail.url == "attachment://gold.webp"
    assert "Empty" in equipped_field.value
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


def test_shop_embed_uses_requested_empty_equipment_emojis(tmp_path) -> None:
    player = Player(discord_user_id=1, guild_id=10, display_name="Test Player", gold=250)
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(),
    )

    embed = build_shop_embed(
        stock,
        player=player,
        equipment=StubEquipmentService(
            EquipmentItem(
                key="unused",
                name="Unused",
                slot="weapon",
                rarity="common",
                min_level=1,
                max_level=1,
                cost=1,
                hp=0,
                attack=0,
                defense=0,
                speed=0,
            )
        ),
        emoji_service=_equipment_emoji_service(tmp_path),
    )

    equipped = next(field for field in embed.fields if field.name == "Equipped").value
    assert "<:ds_eq_weapon_blade:111111111> Empty" in equipped
    assert "<:ds_eq_shield_ward:222222222> Empty" in equipped
    assert "<:ds_eq_helm_helm:333333333> Empty" in equipped
    assert "<:ds_eq_armor_cuirass:444444444> Empty" in equipped
    assert "<:ds_eq_gloves_gauntlets:777777777> Empty" in equipped
    assert "<:ds_eq_boots_greaves:555555555> Empty" in equipped
    assert "<:ds_eq_trinket_token:666666666> Empty" in equipped


def test_shop_embed_splits_equipped_summary_before_discord_field_limit(tmp_path) -> None:
    slots = ("weapon", "shield", "helm", "armor", "gloves", "boots", "trinket")
    items = tuple(
        EquipmentItem(
            key=f"{slot}-item",
            name=f"Polished {slot.title()} of Midnight Inventory",
            slot=slot,
            rarity="legendary",
            min_level=1,
            max_level=10,
            cost=999,
            hp=10,
            attack=11,
            defense=12,
            speed=13,
            thumbnail_asset=f"equipment.{slot}_custom",
        )
        for slot in slots
    )
    player = Player(
        discord_user_id=1,
        guild_id=10,
        display_name="Test Player",
        gold=250,
        **{slot: f"{slot}-item" for slot in slots},
    )
    stock = ShopStock(
        combat_level=5,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        refreshes_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        items=(),
    )
    emoji_keys = [*(f"equipment.{slot}_custom" for slot in slots), "equipment.legendary", "misc.gold"]
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                key: EmojiDefinition(
                    key=key,
                    name=f"ds_{key.replace('.', '_')}",
                    path=tmp_path / f"{key.replace('.', '_')}.png",
                    alt_text=key,
                )
                for key in emoji_keys
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                key: EmojiRegistryEntry(
                    key=key,
                    name=f"ds_{key.replace('.', '_')}",
                    emoji_id=f"15241145836677366{index:02}",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                )
                for index, key in enumerate(emoji_keys)
            },
        ),
    )

    embed = build_shop_embed(
        stock,
        player=player,
        equipment=StubEquipmentService(*items),
        emoji_service=emoji_service,
    )

    equipped_fields = [field for field in embed.fields if field.name.startswith("Equipped")]
    equipped_text = "\n".join(field.value for field in equipped_fields)

    assert len(equipped_fields) > 1
    assert all(len(field.value) <= 1024 for field in equipped_fields)
    assert all(item.name in equipped_text for item in items)


def test_shop_embed_selected_purchase_shows_net_trade_in_price(tmp_path) -> None:
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

    embed = build_shop_embed(
        stock,
        player=player,
        equipment=StubEquipmentService(replaced_item),
        selected_quote=quote,
        emoji_service=_equipment_emoji_service(tmp_path),
    )

    selected_field = next(field for field in embed.fields if field.name.endswith("Selected Purchase"))
    lines = selected_field.value.splitlines()

    assert lines[0] == "<:ds_e_legendary:888888885> ⚔️ Heroic Blade"
    assert lines[1] == "HP 4 | ATK 8 | DEF 3 | SPD 2"
    assert lines[2] == "Purchase Price After Trade-in <:ds_m_gold:999999999> 135"
    assert "Purchase Price After Trade-in <:ds_m_gold:999999999> 135" in selected_field.value
    assert "Sticker" not in selected_field.value
    assert "Trade-in -" not in selected_field.value
    assert "After Purchase" not in selected_field.value


def test_shop_embed_uses_registered_custom_equipment_emoji(tmp_path) -> None:
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
        thumbnail_asset="equipment.weapon_axe",
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
        items=(item,),
    )
    quote = ShopPurchaseQuote(
        item=item,
        replaced_item=None,
        stock=stock,
        trade_in_value=0,
        purchase_cost=140,
    )
    emoji_service = DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "equipment.weapon_axe": EmojiDefinition(
                    key="equipment.weapon_axe",
                    name="ds_eq_weapon_axe",
                    path=tmp_path / "weapon_axe.png",
                    alt_text="Weapon axe",
                ),
                "equipment.legendary": EmojiDefinition(
                    key="equipment.legendary",
                    name="ds_e_legendary",
                    path=tmp_path / "legendary.png",
                    alt_text="Legendary",
                ),
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "equipment.weapon_axe": EmojiRegistryEntry(
                    key="equipment.weapon_axe",
                    name="ds_eq_weapon_axe",
                    emoji_id="987654321",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                ),
                "equipment.legendary": EmojiRegistryEntry(
                    key="equipment.legendary",
                    name="ds_e_legendary",
                    emoji_id="888888885",
                    sha256="a" * 64,
                    animated=False,
                    uploaded_at="2026-07-06T00:00:00+00:00",
                ),
            },
        ),
    )

    embed = build_shop_embed(
        stock,
        player=player,
        equipment=StubEquipmentService(item),
        selected_quote=quote,
        emoji_service=emoji_service,
    )

    fields = {field.name: field.value for field in embed.fields}
    assert fields["Equipped"].startswith("<:ds_e_legendary:888888885> <:ds_eq_weapon_axe:987654321> Heroic Blade")
    assert fields["____________\nSelected Purchase"].startswith(
        "<:ds_e_legendary:888888885> <:ds_eq_weapon_axe:987654321> Heroic Blade"
    )


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
    stats_field = next(field for field in embed.fields if field.name == "Stats")
    assert stats_field.value == "HP 4 | ATK 8 | DEF 3 | SPD 2"
    assert stats_field.inline is False


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

    assert trade_in_field.value.endswith(" 14")
    assert "ds_m_gold" in trade_in_field.value
    assert cost_field.value.endswith(" 126")
    assert "ds_m_gold" in cost_field.value
