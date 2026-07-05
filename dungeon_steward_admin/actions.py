from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from dungeon_steward_admin.context import AdminContext
from dungeon_steward_admin.operations import AdminGameService
from dungeon_steward_admin.permissions import require_permission

ActionCallable = Callable[[AdminContext, Session, dict[str, Any]], "ActionResult"]


@dataclass(frozen=True)
class ActionResult:
    success: bool
    message: str
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class AdminAction:
    name: str
    target: str
    permission: str
    requires_confirmation: bool
    production_allowed: bool
    handler: ActionCallable


ACTION_REGISTRY: dict[str, AdminAction] = {}


def admin_action(
    *,
    name: str,
    target: str,
    permission: str = "game_support",
    requires_confirmation: bool = True,
    production_allowed: bool = True,
) -> Callable[[ActionCallable], ActionCallable]:
    def decorator(func: ActionCallable) -> ActionCallable:
        ACTION_REGISTRY[name] = AdminAction(
            name=name,
            target=target,
            permission=permission,
            requires_confirmation=requires_confirmation,
            production_allowed=production_allowed,
            handler=func,
        )
        return func

    return decorator


def registered_actions() -> list[AdminAction]:
    return sorted(ACTION_REGISTRY.values(), key=lambda action: action.name)


def execute_action(
    context: AdminContext,
    session: Session,
    action_name: str,
    values: dict[str, Any],
    *,
    confirmed: bool = False,
) -> ActionResult:
    action = ACTION_REGISTRY[action_name]
    require_permission(context.config.admin, action.permission, read_only=context.read_only)
    if context.config.is_production and not action.production_allowed:
        return ActionResult(False, f"{action.name} is disabled in production.")
    if action.requires_confirmation and not confirmed:
        return ActionResult(False, f"{action.name} requires confirmation.")
    return action.handler(context, session, values)


@admin_action(name="Grant Gold", target="user", permission="game_support", requires_confirmation=True)
def grant_gold_action(context: AdminContext, session: Session, values: dict[str, Any]) -> ActionResult:
    player = AdminGameService().grant_gold(
        session,
        context,
        player_id=int(values["player_id"]),
        amount=int(values["amount"]),
        reason=str(values.get("reason") or "Admin gold adjustment"),
    )
    return ActionResult(True, f"Gold is now {player.gold}.", {"player_id": player.id, "gold": player.gold})


@admin_action(name="Grant Combat XP", target="user", permission="game_support", requires_confirmation=True)
def grant_combat_xp_action(context: AdminContext, session: Session, values: dict[str, Any]) -> ActionResult:
    levels, points = AdminGameService().grant_combat_xp(
        session,
        context,
        player_id=int(values["player_id"]),
        amount=int(values["amount"]),
        reason=str(values.get("reason") or "Admin combat XP grant"),
    )
    return ActionResult(True, f"Gained {levels} level(s) and {points} stat point(s).")


@admin_action(name="Reset Active Defense", target="user", permission="game_support", requires_confirmation=True)
def reset_active_defense_action(context: AdminContext, session: Session, values: dict[str, Any]) -> ActionResult:
    player = AdminGameService().reset_active_defense(
        session,
        context,
        player_id=int(values["player_id"]),
        reason=str(values.get("reason") or "Admin defense reset"),
    )
    return ActionResult(True, f"Defense reset for {player.display_name}.")


@admin_action(name="Recalculate Combat Progression", target="user", permission="game_support", requires_confirmation=False)
def recalculate_combat_progression_action(context: AdminContext, session: Session, values: dict[str, Any]) -> ActionResult:
    player = AdminGameService().recalculate_combat_progression(
        session,
        context,
        player_id=int(values["player_id"]),
        reason=str(values.get("reason") or "Admin progression recalculation"),
    )
    return ActionResult(True, f"Combat progression recalculated for {player.display_name}.")


@admin_action(name="End Potion Effect", target="potion_activation", permission="game_support", requires_confirmation=True)
def end_potion_effect_action(context: AdminContext, session: Session, values: dict[str, Any]) -> ActionResult:
    activation = AdminGameService().end_potion_effect(
        session,
        context,
        activation_id=int(values["activation_id"]),
        reason=str(values.get("reason") or "Admin ended potion effect"),
    )
    return ActionResult(True, f"Potion activation {activation.id} ended.")
