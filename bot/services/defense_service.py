from __future__ import annotations

import random
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import Player
from bot.services.combat_service import BattleResult, resolve_battle
from bot.services.enemy_service import DUNGEON_LEVEL_MAX, DUNGEON_LEVEL_MIN, generate_enemy
from bot.services.equipment_service import CombatStats, get_effective_combat_stats
from bot.services.player_service import PlayerService
from bot.services.progression_service import (
    calculate_post_defeat_hp,
    get_max_defense_minutes,
    grant_combat_xp,
    sync_combat_progression,
)
from bot.utils.time import ensure_utc, utc_now


class DefenseError(Exception):
    pass


class AlreadyDefendingError(DefenseError):
    pass


class NotDefendingError(DefenseError):
    pass


class InvalidDungeonLevelError(DefenseError):
    pass


@dataclass(frozen=True)
class StartedDefense:
    player_id: int
    session_id: str
    dungeon_level: int
    started_at: datetime
    max_ends_at: datetime
    current_hp: int
    stats: CombatStats


@dataclass(frozen=True)
class DefenseReport:
    player_id: int
    session_id: str
    dungeon_level: int
    started_at: datetime
    ended_at: datetime
    reason: str
    elapsed_seconds: int
    capped_seconds: int
    scheduled_battles: int
    completed_battles: int
    victories: int
    defeats: int
    draws: int
    unresolved_attacks: int
    combat_xp_earned: int
    gold_earned: int
    combat_levels_gained: int
    stat_points_earned: int
    starting_hp: int
    ending_hp: int
    max_hp: int
    enemies_encountered: dict[str, int]
    notable_battles: tuple[str, ...]


class DefenseService:
    def __init__(self, *, players: PlayerService | None = None) -> None:
        self.players = players or PlayerService()

    def start(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        dungeon_level: int,
        channel_id: int | None = None,
        message_id: int | None = None,
        now: datetime | None = None,
    ) -> StartedDefense:
        self._validate_dungeon_level(dungeon_level)
        now = ensure_utc(now or utc_now())
        player = self.players.get_or_create(
            session,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
        )
        if player.is_defending:
            raise AlreadyDefendingError

        sync_combat_progression(player)
        if player.current_hp <= 0:
            player.current_hp = _safe_recovery_hp(player.max_hp)

        session_id = secrets.token_urlsafe(24)
        player.is_defending = True
        player.defense_started_at = now
        player.defense_selected_dungeon_level = dungeon_level
        player.defense_starting_hp = player.current_hp
        player.defense_session_id = session_id
        player.defense_channel_id = channel_id
        player.defense_guild_id = guild_id
        player.defense_message_id = message_id
        session.flush()

        stats = get_effective_combat_stats(player)
        max_ends_at = now + timedelta(minutes=get_max_defense_minutes(player.combat_level))
        return StartedDefense(
            player_id=player.id,
            session_id=session_id,
            dungeon_level=dungeon_level,
            started_at=now,
            max_ends_at=max_ends_at,
            current_hp=player.current_hp,
            stats=stats,
        )

    def stop(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> DefenseReport:
        player = session.scalar(
            select(Player)
            .where(Player.guild_id == guild_id, Player.discord_user_id == user_id)
            .with_for_update()
        )
        if player is None or not player.is_defending:
            raise NotDefendingError
        report = self.resolve_active(
            session,
            player,
            reason="manual stop",
            now=now,
            rng=rng,
        )
        if report is None:
            raise NotDefendingError
        return report

    def resolve_before_explore(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> DefenseReport | None:
        player = self.players.get_or_create(
            session,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
        )
        return self.resolve_active(
            session,
            player,
            reason="exploration",
            now=now,
            rng=rng,
        )

    def resolve_if_expired(
        self,
        session: Session,
        player: Player,
        *,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> DefenseReport | None:
        if not player.is_defending or player.defense_started_at is None:
            return None
        now = ensure_utc(now or utc_now())
        started_at = ensure_utc(player.defense_started_at)
        max_seconds = get_max_defense_minutes(player.combat_level) * 60
        if int((now - started_at).total_seconds()) < max_seconds:
            return None
        return self.resolve_active(
            session,
            player,
            reason="duration cap",
            now=now,
            rng=rng,
        )

    def resolve_expired_sessions(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        limit: int = 25,
        rng: random.Random | None = None,
    ) -> list[DefenseReport]:
        now = ensure_utc(now or utc_now())
        reports: list[DefenseReport] = []
        players = session.scalars(
            select(Player)
            .where(Player.is_defending.is_(True), Player.defense_started_at.is_not(None))
            .order_by(Player.defense_started_at)
            .limit(limit)
            .with_for_update()
        ).all()
        for player in players:
            started_at = ensure_utc(player.defense_started_at)
            max_seconds = get_max_defense_minutes(player.combat_level) * 60
            if int((now - started_at).total_seconds()) >= max_seconds:
                report = self.resolve_active(
                    session,
                    player,
                    reason="duration cap",
                    now=now,
                    rng=rng,
                )
                if report is not None:
                    reports.append(report)
        return reports

    def resolve_active(
        self,
        session: Session,
        player: Player,
        *,
        reason: str,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> DefenseReport | None:
        if not player.is_defending or player.defense_started_at is None:
            return None

        now = ensure_utc(now or utc_now())
        rng = rng or random
        sync_combat_progression(player)
        session_id = player.defense_session_id or secrets.token_urlsafe(24)
        dungeon_level = player.defense_selected_dungeon_level or DUNGEON_LEVEL_MIN
        self._validate_dungeon_level(dungeon_level)
        started_at = ensure_utc(player.defense_started_at)
        starting_hp = player.defense_starting_hp or player.current_hp
        max_seconds = get_max_defense_minutes(player.combat_level) * 60
        elapsed_seconds = max(0, int((now - started_at).total_seconds()))
        capped_seconds = min(elapsed_seconds, max_seconds)
        scheduled_battles = capped_seconds // 60

        stats = get_effective_combat_stats(player)
        player_hp = min(max(0, player.current_hp), stats.max_hp)
        enemies: Counter[str] = Counter()
        notable_battles: list[str] = []
        victories = defeats = draws = 0
        combat_xp_earned = 0
        gold_earned = 0
        completed_battles = 0

        for battle_index in range(1, scheduled_battles + 1):
            enemy = generate_enemy(dungeon_level, rng=rng)
            battle = resolve_battle(
                player_stats=stats,
                player_hp=player_hp,
                enemy=enemy,
                rng=rng,
            )
            completed_battles += 1
            enemies[enemy.name] += 1
            player_hp = battle.player_hp
            combat_xp_earned += battle.combat_xp
            gold_earned += battle.gold
            if battle.outcome == "victory":
                victories += 1
            elif battle.outcome == "defeat":
                defeats += 1
            else:
                draws += 1
            if len(notable_battles) < 3:
                notable_battles.append(_battle_summary(battle, battle_index))
            if battle.outcome == "defeat":
                break

        player.gold += gold_earned
        player.current_hp = max(0, player_hp)
        levels_gained, stat_points_earned = grant_combat_xp(player, combat_xp_earned)
        if defeats:
            player.current_hp = _safe_recovery_hp(player.max_hp)

        ending_hp = player.current_hp
        max_hp = player.max_hp
        unresolved_attacks = max(0, scheduled_battles - completed_battles)
        self._clear_defense(player)
        session.flush()

        return DefenseReport(
            player_id=player.id,
            session_id=session_id,
            dungeon_level=dungeon_level,
            started_at=started_at,
            ended_at=now,
            reason=reason,
            elapsed_seconds=elapsed_seconds,
            capped_seconds=capped_seconds,
            scheduled_battles=scheduled_battles,
            completed_battles=completed_battles,
            victories=victories,
            defeats=defeats,
            draws=draws,
            unresolved_attacks=unresolved_attacks,
            combat_xp_earned=combat_xp_earned,
            gold_earned=gold_earned,
            combat_levels_gained=levels_gained,
            stat_points_earned=stat_points_earned,
            starting_hp=starting_hp,
            ending_hp=ending_hp,
            max_hp=max_hp,
            enemies_encountered=dict(enemies),
            notable_battles=tuple(notable_battles),
        )

    def _validate_dungeon_level(self, dungeon_level: int) -> None:
        if not DUNGEON_LEVEL_MIN <= dungeon_level <= DUNGEON_LEVEL_MAX:
            raise InvalidDungeonLevelError("Dungeon level must be between 1 and 20")

    def _clear_defense(self, player: Player) -> None:
        player.is_defending = False
        player.defense_started_at = None
        player.defense_selected_dungeon_level = None
        player.defense_starting_hp = None
        player.defense_session_id = None
        player.defense_channel_id = None
        player.defense_guild_id = None
        player.defense_message_id = None


def _safe_recovery_hp(max_hp: int) -> int:
    return calculate_post_defeat_hp(max_hp)


def _battle_summary(battle: BattleResult, battle_index: int) -> str:
    if battle.outcome == "victory":
        outcome = "won"
    elif battle.outcome == "defeat":
        outcome = "lost"
    else:
        outcome = "drew"
    return (
        f"Battle {battle_index}: {outcome} against "
        f"{battle.enemy.name} Lv. {battle.enemy.level} in {battle.rounds} rounds"
    )
