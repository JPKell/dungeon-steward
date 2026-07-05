from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import Player
from bot.services.equipment_service import EQUIPMENT_SLOTS, EquipmentItem, EquipmentService
from bot.services.player_service import PlayerService
from bot.services.progression_content import PROGRESSION_CONTENT
from bot.services.progression_service import sync_combat_progression
from bot.services.shop_selection import select_shop_items
from bot.utils.time import ensure_utc, utc_now

SHOP_STOCK_SIZE = PROGRESSION_CONTENT.shop.stock_size
SLOT_ORDER = {slot: index for index, slot in enumerate(EQUIPMENT_SLOTS)}


class ShopError(Exception):
    pass


class InvalidShopSelectionError(ShopError):
    pass


class InsufficientGoldError(ShopError):
    pass


@dataclass(frozen=True)
class ShopStock:
    combat_level: int
    generated_at: datetime
    refreshes_at: datetime
    items: tuple[EquipmentItem, ...]


@dataclass(frozen=True)
class PurchasedEquipment:
    item: EquipmentItem
    replaced_item: EquipmentItem | None
    remaining_gold: int
    stock: ShopStock
    trade_in_value: int = 0
    purchase_cost: int = 0


class ShopService:
    def __init__(
        self,
        *,
        equipment: EquipmentService | None = None,
        players: PlayerService | None = None,
    ) -> None:
        self.equipment = equipment or EquipmentService()
        self.players = players or PlayerService()

    def stock_for_player(self, player: Player, *, now: datetime | None = None) -> ShopStock:
        sync_combat_progression(player)
        return self.stock_for_level(player.combat_level, now=now)

    def stock_for_level(self, combat_level: int, *, now: datetime | None = None) -> ShopStock:
        generated_at = shop_hour(now or utc_now())
        refreshes_at = generated_at + timedelta(hours=1)
        level = max(1, combat_level)

        rng = random.Random(_shop_seed(generated_at, level))
        selected = select_shop_items(
            [_item_mapping(item) for item in self.equipment.items],
            shop_level=level,
            rng=rng,
            stock_size=SHOP_STOCK_SIZE,
        )
        stock = [self.equipment.get(str(item["key"])) for item in selected]
        scaled_stock = [self.equipment.scaled_for_combat_level(item, level) for item in stock]
        scaled_stock.sort(key=lambda item: (SLOT_ORDER.get(item.slot, len(SLOT_ORDER)), item.cost))
        return ShopStock(
            combat_level=level,
            generated_at=generated_at,
            refreshes_at=refreshes_at,
            items=tuple(scaled_stock),
        )

    def purchase(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        stock_number: int,
        now: datetime | None = None,
    ) -> PurchasedEquipment:
        if not 1 <= stock_number <= SHOP_STOCK_SIZE:
            raise InvalidShopSelectionError("Choose a shop item from 1 through 10")

        player = session.scalar(select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id).with_for_update())
        if player is None:
            player = self.players.get_or_create(
                session,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
        stock = self.stock_for_player(player, now=now)
        try:
            item = stock.items[stock_number - 1]
        except IndexError as error:
            raise InvalidShopSelectionError("That shop item is no longer available") from error

        if player.gold < item.cost:
            raise InsufficientGoldError("You do not have enough gold for that item")

        replaced_item = self.equipment.get_or_none(getattr(player, item.slot), combat_level=player.combat_level)
        trade_in_value = 0
        purchase_cost = item.cost
        if replaced_item is not None:
            trade_in_value = int(item.cost * 0.1)
            purchase_cost = max(0, item.cost - trade_in_value)
        player.gold -= purchase_cost
        setattr(player, item.slot, item.key)
        session.flush()
        return PurchasedEquipment(
            item=item,
            replaced_item=replaced_item,
            remaining_gold=player.gold,
            stock=stock,
            trade_in_value=trade_in_value,
            purchase_cost=purchase_cost,
        )


def shop_hour(when: datetime) -> datetime:
    value = ensure_utc(when)
    return value.replace(minute=0, second=0, microsecond=0)


def _shop_seed(generated_at: datetime, combat_level: int) -> str:
    return f"dungeon-steward-shop:{int(generated_at.timestamp())}:combat-level:{combat_level}"


def _item_mapping(item: EquipmentItem) -> dict[str, str | int]:
    return {
        "key": item.key,
        "name": item.name,
        "slot": item.slot,
        "rarity": item.rarity,
        "min_level": item.min_level,
        "max_level": item.max_level,
        "cost": item.cost,
        "hp": item.hp,
        "attack": item.attack,
        "defense": item.defense,
        "speed": item.speed,
    }
