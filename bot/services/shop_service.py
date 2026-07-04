from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import Player
from bot.services.equipment_service import EquipmentItem, EquipmentService
from bot.services.player_service import PlayerService
from bot.services.progression_content import PROGRESSION_CONTENT
from bot.services.progression_service import sync_combat_progression
from bot.utils.time import ensure_utc, utc_now

SHOP_STOCK_SIZE = PROGRESSION_CONTENT.shop.stock_size
RARITY_WEIGHTS = PROGRESSION_CONTENT.shop.rarity_weights


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
        eligible = self.equipment.eligible_for_level(level)
        if len(eligible) < SHOP_STOCK_SIZE:
            eligible = [item for item in self.equipment.items if item.min_level <= level]
        if len(eligible) < SHOP_STOCK_SIZE:
            eligible = self.equipment.items

        rng = random.Random(_shop_seed(generated_at, level))
        stock = _weighted_sample_without_replacement(
            rng,
            eligible,
            min(SHOP_STOCK_SIZE, len(eligible)),
        )
        scaled_stock = [self.equipment.scaled_for_combat_level(item, level) for item in stock]
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

        player = session.scalar(
            select(Player)
            .where(Player.guild_id == guild_id, Player.discord_user_id == user_id)
            .with_for_update()
        )
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
        player.gold -= item.cost
        setattr(player, item.slot, item.key)
        session.flush()
        return PurchasedEquipment(
            item=item,
            replaced_item=replaced_item,
            remaining_gold=player.gold,
            stock=stock,
        )


def shop_hour(when: datetime) -> datetime:
    value = ensure_utc(when)
    return value.replace(minute=0, second=0, microsecond=0)


def _shop_seed(generated_at: datetime, combat_level: int) -> str:
    return f"dungeon-steward-shop:{int(generated_at.timestamp())}:combat-level:{combat_level}"


def _weighted_sample_without_replacement(
    rng: random.Random,
    items: list[EquipmentItem],
    count: int,
) -> list[EquipmentItem]:
    pool = list(items)
    selected: list[EquipmentItem] = []
    for _ in range(count):
        weights = [RARITY_WEIGHTS[item.rarity] for item in pool]
        item = rng.choices(pool, weights=weights, k=1)[0]
        selected.append(item)
        pool.remove(item)
    return selected
