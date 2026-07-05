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
from bot.services.dungeon_progression_service import can_enter_dungeon, sync_player_dungeon_progression
from bot.services.enemy_service import DUNGEON_LEVEL_MAX, DUNGEON_LEVEL_MIN, generate_enemy
from bot.services.equipment_service import CombatStats, get_effective_combat_stats
from bot.services.player_service import PlayerService
from bot.services.potion_service import ActivePotion, PotionService
from bot.services.progression_content import PROGRESSION_CONTENT
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


class InvalidDefenseTimestampError(DefenseError):
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
class StartedDefenseResult:
    started: StartedDefense
    resolved_previous: DefenseReport | None


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
    potion_effects: tuple[str, ...] = ()
    potion_healing: int = 0
    potion_luck_procs: int = 0
    potion_bonus_combat_xp: int = 0
    max_hp_effect_expired: bool = False


class DefenseService:
    def __init__(self, *, players: PlayerService | None = None, potions: PotionService | None = None) -> None:
        self.players = players or PlayerService()
        self.potions = potions or PotionService()

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
        sync_player_dungeon_progression(player)
        if not can_enter_dungeon(dungeon_level, player.highest_unlocked_dungeon_level):
            raise InvalidDungeonLevelError("That dungeon level is not unlocked")
        stats = self.potions.apply_effects_to_stats(
            get_effective_combat_stats(player),
            self.potions.active_effects_at(session, player, now),
        )
        if PROGRESSION_CONTENT.defense.restore_full_hp_on_start:
            player.current_hp = stats.max_hp
            starting_hp = stats.max_hp
        else:
            if player.current_hp <= 0:
                player.current_hp = _safe_recovery_hp(stats.max_hp)
            starting_hp = min(stats.max_hp, max(1, player.current_hp))

        session_id = secrets.token_urlsafe(24)
        player.is_defending = True
        player.defense_started_at = now
        player.defense_selected_dungeon_level = dungeon_level
        player.defense_starting_hp = starting_hp
        player.defense_session_id = session_id
        player.defense_channel_id = channel_id
        player.defense_guild_id = guild_id
        player.defense_message_id = message_id
        session.flush()

        max_ends_at = now + timedelta(minutes=get_max_defense_minutes(player.combat_level))
        return StartedDefense(
            player_id=player.id,
            session_id=session_id,
            dungeon_level=dungeon_level,
            started_at=now,
            max_ends_at=max_ends_at,
            current_hp=starting_hp,
            stats=stats,
        )

    def start_after_resolving(
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
        rng: random.Random | None = None,
    ) -> StartedDefenseResult:
        now = ensure_utc(now or utc_now())
        player = session.scalar(select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id).with_for_update())
        if player is None:
            player = self.players.get_or_create(
                session,
                guild_id=guild_id,
                user_id=user_id,
                display_name=display_name,
            )
        else:
            player.display_name = display_name[:120]

        report = None
        if player.is_defending:
            report = self.resolve_active(
                session,
                player,
                reason="new defense",
                now=now,
                rng=rng,
            )
        started = self.start(
            session,
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
            dungeon_level=dungeon_level,
            channel_id=channel_id,
            message_id=message_id,
            now=now,
        )
        return StartedDefenseResult(started=started, resolved_previous=report)

    def stop(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> DefenseReport:
        player = session.scalar(select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id).with_for_update())
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
        player = session.scalar(select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id).with_for_update())
        if player is None:
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
        try:
            started_at = _validated_started_at(player.defense_started_at, now=now)
        except InvalidDefenseTimestampError:
            self._clear_defense(player)
            session.flush()
            return None
        max_seconds = get_max_defense_minutes(player.combat_level) * 60
        if _safe_elapsed_seconds(started_at, now) < max_seconds:
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
            try:
                started_at = _validated_started_at(player.defense_started_at, now=now)
            except InvalidDefenseTimestampError:
                self._clear_defense(player)
                session.flush()
                continue
            max_seconds = get_max_defense_minutes(player.combat_level) * 60
            if _safe_elapsed_seconds(started_at, now) >= max_seconds:
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
        try:
            started_at = _validated_started_at(player.defense_started_at, now=now)
        except InvalidDefenseTimestampError:
            self._clear_defense(player)
            session.flush()
            raise
        max_seconds = get_max_defense_minutes(player.combat_level) * 60
        elapsed_seconds = _safe_elapsed_seconds(started_at, now)
        capped_seconds = min(elapsed_seconds, max_seconds)
        scheduled_battles = capped_seconds // 60

        base_stats = get_effective_combat_stats(player)
        history = self.potions.activation_history(
            session,
            player,
            start=started_at,
            end=now + timedelta(seconds=1),
        )
        start_effects = self.potions.active_from_history(history, started_at)
        start_stats = self.potions.apply_effects_to_stats(base_stats, start_effects)
        starting_hp = min(
            start_stats.max_hp,
            max(1, int(player.defense_starting_hp or start_stats.max_hp)),
        )
        player_hp = starting_hp
        previous_max_hp = start_stats.max_hp
        last_battle_stats = start_stats
        enemies: Counter[str] = Counter()
        notable_battles: list[str] = []
        potion_effects: dict[str, str] = {}
        _record_potion_effects(potion_effects, start_effects)
        victories = defeats = draws = 0
        combat_xp_earned = 0
        gold_earned = 0
        completed_battles = 0
        potion_healing = 0
        potion_luck_procs = 0
        potion_bonus_combat_xp = 0
        max_hp_effect_expired = False

        for battle_index in range(1, scheduled_battles + 1):
            battle_time = started_at + timedelta(minutes=battle_index)
            active_effects = self.potions.active_from_history(history, battle_time)
            _record_potion_effects(potion_effects, active_effects)
            stats = self.potions.apply_effects_to_stats(base_stats, active_effects)
            if stats.max_hp < previous_max_hp:
                max_hp_effect_expired = True
            player_hp = min(stats.max_hp, max(0, player_hp))
            previous_max_hp = stats.max_hp
            last_battle_stats = stats
            enemy = generate_enemy(dungeon_level, rng=rng)
            luck_proc = False
            luck_chance = self.potions.luck_chance(active_effects)
            if luck_chance > 0 and rng.random() < luck_chance:
                luck_proc = True
            battle = resolve_battle(
                player_stats=stats,
                player_hp=player_hp,
                enemy=enemy,
                rng=rng,
                reward_combat_xp=_enemy_max_combat_xp(enemy) if luck_proc else None,
                reward_gold=_enemy_max_gold(enemy) if luck_proc else None,
                combat_xp_multiplier=self.potions.combat_xp_multiplier(active_effects),
                luck_proc=luck_proc,
            )
            completed_battles += 1
            enemies[enemy.name] += 1
            player_hp = battle.player_hp
            if battle.outcome == "victory":
                healing = self.potions.healing_amount(active_effects, active_max_hp=stats.max_hp)
                if healing > 0:
                    healed_hp = min(stats.max_hp, player_hp + healing)
                    potion_healing += max(0, healed_hp - player_hp)
                    player_hp = healed_hp
            combat_xp_earned += battle.combat_xp
            gold_earned += battle.gold
            potion_bonus_combat_xp += battle.potion_bonus_xp
            if battle.luck_proc:
                potion_luck_procs += 1
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

        battle_end_at = started_at + timedelta(seconds=capped_seconds)
        battle_end_effects = self.potions.active_from_history(history, battle_end_at)
        battle_end_stats = self.potions.apply_effects_to_stats(base_stats, battle_end_effects)
        if battle_end_stats.max_hp < last_battle_stats.max_hp:
            max_hp_effect_expired = True
        battle_ending_hp = min(battle_end_stats.max_hp, max(0, player_hp))
        player.gold += gold_earned
        player.defense_wins += victories
        player.current_hp = battle_ending_hp
        levels_gained, stat_points_earned = grant_combat_xp(player, combat_xp_earned)
        final_base_stats = get_effective_combat_stats(player)
        report_stats = self.potions.apply_effects_to_stats(final_base_stats, battle_end_effects)
        current_stats = self.potions.apply_effects_to_stats(
            final_base_stats,
            self.potions.active_from_history(history, now),
        )
        ending_hp = min(report_stats.max_hp, battle_ending_hp)
        if defeats:
            player.current_hp = current_stats.max_hp
        elif levels_gained:
            player.current_hp = current_stats.max_hp
        else:
            player.current_hp = min(current_stats.max_hp, ending_hp)
        if victories > 0 and defeats == 0:
            player.highest_completed_dungeon_level = max(
                player.highest_completed_dungeon_level,
                dungeon_level,
            )
        sync_player_dungeon_progression(player)

        max_hp = report_stats.max_hp
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
            potion_effects=tuple(potion_effects.values()),
            potion_healing=potion_healing,
            potion_luck_procs=potion_luck_procs,
            potion_bonus_combat_xp=potion_bonus_combat_xp,
            max_hp_effect_expired=max_hp_effect_expired,
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
    return f"Battle {battle_index}: {outcome} against {battle.enemy.name} Lv. {battle.enemy.level} in {battle.rounds} rounds"


def _record_potion_effects(target: dict[str, str], active_effects: tuple[ActivePotion, ...]) -> None:
    for active in active_effects:
        target[active.effect_group] = f"{active.item.name} ({active.effect_group})"


def _enemy_max_combat_xp(enemy) -> int:
    return max(int(enemy.combat_xp), int(getattr(enemy, "max_combat_xp", enemy.combat_xp) or 0))


def _enemy_max_gold(enemy) -> int:
    return max(int(enemy.gold), int(getattr(enemy, "max_gold", enemy.gold) or 0))


def _validated_started_at(value: datetime | None, *, now: datetime) -> datetime:
    if value is None:
        raise InvalidDefenseTimestampError("Defense start timestamp is missing")
    try:
        started_at = ensure_utc(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidDefenseTimestampError("Defense start timestamp is invalid") from exc
    # Small future skew is treated as zero elapsed time. Larger skew indicates corrupt data.
    if (started_at - now).total_seconds() > 300:
        raise InvalidDefenseTimestampError("Defense start timestamp is too far in the future")
    return started_at


def _safe_elapsed_seconds(started_at: datetime, now: datetime) -> int:
    try:
        elapsed = int((now - started_at).total_seconds())
    except (OverflowError, OSError) as exc:
        raise InvalidDefenseTimestampError("Defense elapsed time could not be calculated") from exc
    if elapsed <= 0:
        return 0
    maximum = PROGRESSION_CONTENT.defense.maximum_elapsed_days * 24 * 60 * 60
    return min(elapsed, maximum)
