from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, inspect, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from bot.models import Player, PotionActivation, PotionInventoryStack
from bot.services.equipment_service import EQUIPMENT_SLOTS, EquipmentService
from bot.services.potion_service import PotionService
from bot.services.progression_service import grant_combat_xp, sync_combat_progression
from bot.utils.time import utc_now
from dungeon_steward_admin.audit import AuditRecord, write_audit
from dungeon_steward_admin.context import AdminContext
from dungeon_steward_admin.permissions import require_permission


class AdminOperationError(Exception):
    pass


class InvalidItemError(AdminOperationError):
    pass


class InvalidQuantityError(AdminOperationError):
    pass


@dataclass(frozen=True)
class UserSearchRow:
    id: int
    guild_id: int
    discord_user_id: int
    display_name: str
    combat_level: int
    explore_level: int
    gold: int
    is_active: bool


@dataclass(frozen=True)
class UserSummary:
    player_id: int
    guild_id: int
    discord_user_id: int
    display_name: str
    is_active: bool
    created_at: datetime | None
    last_activity: datetime | None
    explore_level: int
    combat_level: int
    hp: str
    gold: int
    is_defending: bool
    active_potions: tuple[str, ...]
    inventory_count: int | None
    equipment_count: int
    potion_schema_warning: str | None = None


class AdminGameService:
    def __init__(
        self,
        *,
        potions: PotionService | None = None,
        equipment: EquipmentService | None = None,
    ) -> None:
        self.potions = potions or PotionService()
        self.equipment = equipment or EquipmentService()

    def search_users(
        self,
        session: Session,
        query: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> list[UserSearchRow]:
        query = (query or "").strip()
        statement = select(Player)
        if query:
            conditions = [Player.display_name.ilike(f"%{query}%")]
            numeric = int(query) if query.isdigit() else None
            if numeric is not None:
                conditions.extend([Player.id == numeric, Player.discord_user_id == numeric, Player.guild_id == numeric])
                priority = case(
                    (Player.id == numeric, 0),
                    (Player.discord_user_id == numeric, 1),
                    (Player.guild_id == numeric, 2),
                    (func.lower(Player.display_name) == query.lower(), 3),
                    else_=4,
                )
            else:
                priority = case((func.lower(Player.display_name) == query.lower(), 0), else_=1)
            statement = statement.where(or_(*conditions)).order_by(priority, Player.display_name, Player.id)
        else:
            statement = statement.order_by(Player.updated_at.desc(), Player.id.desc())
        rows = session.scalars(statement.offset(max(0, offset)).limit(max(1, min(limit, 200)))).all()
        return [
            UserSearchRow(
                id=player.id,
                guild_id=player.guild_id,
                discord_user_id=player.discord_user_id,
                display_name=player.display_name,
                combat_level=player.combat_level,
                explore_level=player.explore_level,
                gold=player.gold,
                is_active=player.is_active,
            )
            for player in rows
        ]

    def user_summary(self, session: Session, player_id: int) -> UserSummary:
        player = _get_player(session, player_id)
        potion_schema_warning = _potion_schema_warning(session)
        active_names: tuple[str, ...] = ()
        inventory_count: int | None = None
        if potion_schema_warning is None:
            try:
                active = self.potions.active_effects_at(session, player)
                active_names = tuple(effect.item.name for effect in active)
                inventory_count = int(
                    session.scalar(
                        select(func.coalesce(func.sum(PotionInventoryStack.quantity), 0)).where(
                            PotionInventoryStack.player_id == player.id
                        )
                    )
                    or 0
                )
            except OperationalError as error:
                session.rollback()
                potion_schema_warning = _schema_operation_warning(error)
        equipment_count = sum(1 for slot in EQUIPMENT_SLOTS if getattr(player, slot) is not None)
        return UserSummary(
            player_id=player.id,
            guild_id=player.guild_id,
            discord_user_id=player.discord_user_id,
            display_name=player.display_name,
            is_active=player.is_active,
            created_at=player.created_at,
            last_activity=player.last_exploration_at,
            explore_level=player.explore_level,
            combat_level=player.combat_level,
            hp=f"{player.current_hp}/{player.max_hp}",
            gold=player.gold,
            is_defending=player.is_defending,
            active_potions=active_names,
            inventory_count=inventory_count,
            equipment_count=equipment_count,
            potion_schema_warning=potion_schema_warning,
        )

    def set_potion_quantity(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        item_key: str,
        quantity: int,
        reason: str,
    ) -> PotionInventoryStack:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        if quantity < 0:
            raise InvalidQuantityError("Potion quantity cannot be negative")
        item = self.potions.get(item_key)
        player = _get_player_for_update(session, player_id)
        stack = _get_or_create_potion_stack(session, player.id, item.key)
        previous = {"item_key": item.key, "quantity": int(stack.quantity or 0)}
        stack.quantity = min(quantity, item.inventory_stack_limit)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="inventory.set_potion_quantity",
                target_domain="inventory",
                target_table=PotionInventoryStack.__tablename__,
                target_user_id=player.id,
                target_record_id=str(stack.id),
                previous_values=previous,
                new_values={"item_key": item.key, "quantity": stack.quantity},
                quantity_changed=stack.quantity - previous["quantity"],
                reason=reason,
            ),
        )
        return stack

    def adjust_potion_quantity(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        item_key: str,
        delta: int,
        reason: str,
    ) -> PotionInventoryStack:
        if delta == 0:
            raise InvalidQuantityError("Potion quantity change cannot be zero")
        player = _get_player(session, player_id)
        stack = session.scalar(
            select(PotionInventoryStack).where(
                PotionInventoryStack.player_id == player.id,
                PotionInventoryStack.item_key == item_key,
            )
        )
        current = int(stack.quantity or 0) if stack else 0
        return self.set_potion_quantity(
            session,
            context,
            player_id=player_id,
            item_key=item_key,
            quantity=current + delta,
            reason=reason,
        )

    def equip_equipment(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        equipment_key: str,
        reason: str,
    ) -> Player:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        item = self.equipment.get(equipment_key)
        player = _get_player_for_update(session, player_id)
        previous_key = getattr(player, item.slot)
        setattr(player, item.slot, item.key)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="equipment.equip",
                target_domain="equipment",
                target_user_id=player.id,
                target_record_id=item.key,
                previous_values={item.slot: previous_key},
                new_values={item.slot: item.key},
                reason=reason,
            ),
        )
        return player

    def unequip_slot(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        slot: str,
        reason: str,
    ) -> Player:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        if slot not in EQUIPMENT_SLOTS:
            raise InvalidItemError(f"Unknown equipment slot: {slot}")
        player = _get_player_for_update(session, player_id)
        previous_key = getattr(player, slot)
        setattr(player, slot, None)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="equipment.unequip",
                target_domain="equipment",
                target_user_id=player.id,
                target_record_id=previous_key,
                previous_values={slot: previous_key},
                new_values={slot: None},
                reason=reason,
            ),
        )
        return player

    def remove_equipped_item(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        equipment_key: str,
        reason: str,
        confirmed: bool = False,
    ) -> Player:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        self.equipment.get(equipment_key)
        player = _get_player_for_update(session, player_id)
        slots = [slot for slot in EQUIPMENT_SLOTS if getattr(player, slot) == equipment_key]
        if slots and not confirmed:
            raise InvalidItemError("Equipment is currently equipped; explicit confirmation is required.")
        previous = {slot: getattr(player, slot) for slot in slots}
        for slot in slots:
            setattr(player, slot, None)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="equipment.remove_equipped",
                target_domain="equipment",
                target_user_id=player.id,
                target_record_id=equipment_key,
                previous_values=previous,
                new_values={slot: None for slot in slots},
                reason=reason,
            ),
        )
        return player

    def grant_gold(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Player:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        if amount == 0:
            raise InvalidQuantityError("Gold change cannot be zero")
        player = _get_player_for_update(session, player_id)
        previous = player.gold
        player.gold = max(0, player.gold + amount)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="currency.adjust_gold",
                target_domain="currency",
                target_user_id=player.id,
                previous_values={"gold": previous},
                new_values={"gold": player.gold},
                quantity_changed=player.gold - previous,
                reason=reason,
            ),
        )
        return player

    def grant_combat_xp(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        amount: int,
        reason: str,
    ) -> tuple[int, int]:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        if amount <= 0:
            raise InvalidQuantityError("Combat XP grant must be positive")
        player = _get_player_for_update(session, player_id)
        previous = {"combat_level": player.combat_level, "combat_xp": player.combat_xp}
        levels, points = grant_combat_xp(player, amount)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="progression.grant_combat_xp",
                target_domain="progression",
                target_user_id=player.id,
                previous_values=previous,
                new_values={
                    "combat_level": player.combat_level,
                    "combat_xp": player.combat_xp,
                    "unspent_stat_points": player.unspent_stat_points,
                },
                quantity_changed=amount,
                reason=reason,
            ),
        )
        return levels, points

    def reset_active_defense(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        reason: str,
    ) -> Player:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        player = _get_player_for_update(session, player_id)
        previous = {
            "is_defending": player.is_defending,
            "defense_started_at": player.defense_started_at,
            "defense_session_id": player.defense_session_id,
        }
        player.is_defending = False
        player.defense_started_at = None
        player.defense_selected_dungeon_level = None
        player.defense_starting_hp = None
        player.defense_session_id = None
        player.defense_channel_id = None
        player.defense_guild_id = None
        player.defense_message_id = None
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="defense.reset_active",
                target_domain="defense",
                target_user_id=player.id,
                previous_values=previous,
                new_values={"is_defending": False},
                reason=reason,
            ),
        )
        return player

    def recalculate_combat_progression(
        self,
        session: Session,
        context: AdminContext,
        *,
        player_id: int,
        reason: str,
    ) -> Player:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        player = _get_player_for_update(session, player_id)
        previous = {
            "combat_level": player.combat_level,
            "combat_xp_to_next_level": player.combat_xp_to_next_level,
            "max_hp": player.max_hp,
            "current_hp": player.current_hp,
        }
        sync_combat_progression(player)
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="progression.recalculate_combat",
                target_domain="progression",
                target_user_id=player.id,
                previous_values=previous,
                new_values={
                    "combat_level": player.combat_level,
                    "combat_xp_to_next_level": player.combat_xp_to_next_level,
                    "max_hp": player.max_hp,
                    "current_hp": player.current_hp,
                },
                reason=reason,
            ),
        )
        return player

    def end_potion_effect(
        self,
        session: Session,
        context: AdminContext,
        *,
        activation_id: int,
        reason: str,
    ) -> PotionActivation:
        require_permission(context.config.admin, "game_support", read_only=context.read_only)
        activation = session.get(PotionActivation, activation_id)
        if activation is None:
            raise InvalidItemError(f"Unknown potion activation: {activation_id}")
        previous = {"effective_ends_at": activation.effective_ends_at}
        activation.effective_ends_at = min(activation.effective_ends_at, utc_now())
        session.flush()
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="inventory.end_potion_effect",
                target_domain="inventory",
                target_table=PotionActivation.__tablename__,
                target_user_id=activation.player_id,
                target_record_id=str(activation.id),
                previous_values=previous,
                new_values={"effective_ends_at": activation.effective_ends_at},
                reason=reason,
            ),
        )
        return activation


def _potion_schema_warning(session: Session) -> str | None:
    required_columns = {
        PotionActivation.__tablename__: {
            "id",
            "player_id",
            "item_key",
            "effect_group",
            "tier",
            "activated_at",
            "original_expires_at",
            "effective_ends_at",
            "idempotency_token",
        },
        PotionInventoryStack.__tablename__: {"id", "player_id", "item_key", "quantity"},
    }
    try:
        inspector = inspect(session.get_bind())
        missing_tables: list[str] = []
        missing_columns: list[str] = []
        for table_name, expected_columns in required_columns.items():
            if not inspector.has_table(table_name):
                missing_tables.append(table_name)
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name in sorted(expected_columns - existing_columns):
                missing_columns.append(f"{table_name}.{column_name}")
    except OperationalError as error:
        return _schema_operation_warning(error)

    if missing_tables:
        return f"Potion tables missing ({', '.join(missing_tables)}); run alembic upgrade head."
    if missing_columns:
        return f"Potion columns missing ({', '.join(missing_columns)}); run alembic upgrade head."
    return None


def _schema_operation_warning(error: OperationalError) -> str:
    detail = str(getattr(error, "orig", error)).strip()
    if detail:
        return f"Potion schema unavailable ({detail}); run alembic upgrade head."
    return "Potion schema unavailable; run alembic upgrade head."


def _get_player(session: Session, player_id: int) -> Player:
    player = session.get(Player, player_id)
    if player is None:
        raise AdminOperationError(f"Unknown player id: {player_id}")
    return player


def _get_player_for_update(session: Session, player_id: int) -> Player:
    player = session.scalar(select(Player).where(Player.id == player_id).with_for_update())
    if player is None:
        raise AdminOperationError(f"Unknown player id: {player_id}")
    return player


def _get_or_create_potion_stack(session: Session, player_id: int, item_key: str) -> PotionInventoryStack:
    stack = session.scalar(
        select(PotionInventoryStack)
        .where(PotionInventoryStack.player_id == player_id, PotionInventoryStack.item_key == item_key)
        .with_for_update()
    )
    if stack is None:
        stack = PotionInventoryStack(player_id=player_id, item_key=item_key, quantity=0)
        session.add(stack)
        session.flush()
    return stack
