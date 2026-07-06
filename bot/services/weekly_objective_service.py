# ruff: noqa: E501
from __future__ import annotations

import json
import logging
import math
import random
import string
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from statistics import median
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from bot.models import Player, WeeklyObjective, WeeklyObjectiveEvent, WeeklyObjectiveReward, WeeklyPlayerContribution
from bot.services.equipment_service import EquipmentItem, EquipmentService
from bot.services.player_service import PlayerService
from bot.utils.time import ensure_utc, is_before_or_equal, utc_now

log = logging.getLogger(__name__)

WEEKLY_OBJECTIVE_SCHEMA_VERSION = 2
WEEKLY_REWARD_POLICY_VERSION = 1
INITIAL_DIFFICULTY_INDEX = 1.0
MIN_DIFFICULTY_INDEX = 0.65
MAX_DIFFICULTY_INDEX = 2.5
SUCCESS_DIFFICULTY_MULTIPLIER = 1.10
FAILURE_DIFFICULTY_MULTIPLIER = 0.85
PARTICIPANT_EXPONENT = 0.85
OBJECTIVE_DURATION = timedelta(days=7)
RECENT_TEMPLATE_COOLDOWN = 12
RECENT_METRIC_COOLDOWN = 4
EFFORT_MULTIPLIERS = {
    1: 0.85,
    2: 0.95,
    3: 1.00,
    4: 1.10,
    5: 1.20,
}


class WeeklyMetric(StrEnum):
    EXPLORATIONS = "explorations"
    EXPLORE_GOLD = "explore_gold"
    EXPLORE_XP = "explore_xp"
    TOTAL_GOLD = "total_gold"
    TOTAL_XP = "total_xp"
    HERO_INFLUENCE_GAINED = "hero_influence_gained"
    HERO_INFLUENCE_REDUCED = "hero_influence_reduced"
    VILLAIN_INFLUENCE_GAINED = "villain_influence_gained"
    VILLAIN_INFLUENCE_REDUCED = "villain_influence_reduced"
    STABILITY_GAINED = "stability_gained"
    DISCOVERIES_FOUND = "discoveries_found"
    UNIQUE_DISCOVERIES_FOUND = "unique_discoveries_found"
    DEFENSE_KILLS = "defense_kills"
    DEFENSE_GOLD = "defense_gold"
    DEFENSE_XP = "defense_xp"


class ObjectiveMode(StrEnum):
    EXPLORE = "explore"
    DEFEND = "defend"
    MIXED = "mixed"


@dataclass(frozen=True)
class ObjectiveTemplate:
    key: str
    title: str
    description_template: str
    metric: WeeklyMetric
    base_target: int
    effort_tier: int
    mode: ObjectiveMode
    round_to: int = 1


@dataclass(frozen=True)
class WeeklyRewardPreview:
    explore_level_used: int
    reference_equipment_cost: int
    effort_multiplier: float
    difficulty_multiplier: float
    gold_awarded: int


OBJECTIVE_TEMPLATES: tuple[ObjectiveTemplate, ...] = (
    ObjectiveTemplate("map_moving_halls", "Map the Moving Halls", "Complete {target} explorations.", WeeklyMetric.EXPLORATIONS, 35, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("survey_lower_passages", "Survey the Lower Passages", "Complete {target} explorations.", WeeklyMetric.EXPLORATIONS, 50, 2, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("audit_quiet_corridors", "Audit the Quiet Corridors", "Complete {target} explorations.", WeeklyMetric.EXPLORATIONS, 65, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("redraw_dungeon_map", "Redraw the Dungeon Map", "Complete {target} explorations.", WeeklyMetric.EXPLORATIONS, 80, 4, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("recover_rent", "Recover the Rent", "Earn {target} gold through exploration.", WeeklyMetric.EXPLORE_GOLD, 1000, 1, ObjectiveMode.EXPLORE, 50),
    ObjectiveTemplate("balance_exploration_coffers", "Balance the Exploration Coffers", "Earn {target} gold through exploration.", WeeklyMetric.EXPLORE_GOLD, 1750, 3, ObjectiveMode.EXPLORE, 50),
    ObjectiveTemplate("fund_repairs_by_wandering", "Fund Repairs by Wandering Around", "Earn {target} gold through exploration.", WeeklyMetric.EXPLORE_GOLD, 2500, 5, ObjectiveMode.EXPLORE, 50),
    ObjectiveTemplate("field_notes", "Take Better Field Notes", "Earn {target} explore XP.", WeeklyMetric.EXPLORE_XP, 250, 1, ObjectiveMode.EXPLORE, 10),
    ObjectiveTemplate("apprentice_ledger", "Fill the Apprentice Ledger", "Earn {target} explore XP.", WeeklyMetric.EXPLORE_XP, 400, 3, ObjectiveMode.EXPLORE, 10),
    ObjectiveTemplate("lessons_from_depths", "Lessons from the Depths", "Earn {target} explore XP.", WeeklyMetric.EXPLORE_XP, 600, 5, ObjectiveMode.EXPLORE, 10),
    ObjectiveTemplate("every_coin_story", "Every Coin Has a Story", "Earn {target} gold from exploration and defense.", WeeklyMetric.TOTAL_GOLD, 2000, 2, ObjectiveMode.MIXED, 50),
    ObjectiveTemplate("treasury_making_noises", "The Treasury Is Making Noises", "Earn {target} gold from exploration and defense.", WeeklyMetric.TOTAL_GOLD, 3500, 4, ObjectiveMode.MIXED, 50),
    ObjectiveTemplate("applied_dungeonkeeping", "Applied Dungeonkeeping", "Earn {target} XP from exploration and defense.", WeeklyMetric.TOTAL_XP, 500, 2, ObjectiveMode.MIXED, 10),
    ObjectiveTemplate("professional_development", "Mandatory Professional Development", "Earn {target} XP from exploration and defense.", WeeklyMetric.TOTAL_XP, 800, 4, ObjectiveMode.MIXED, 10),
    ObjectiveTemplate("welcome_heroes", "Welcome the Heroes", "Increase hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_GAINED, 20, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("advertise_dungeon", "Advertise the Dungeon", "Increase hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_GAINED, 30, 2, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("hero_recruitment_drive", "Hero Recruitment Drive", "Increase hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_GAINED, 40, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("polish_hero_reputation", "Polish the Heroic Reputation", "Increase hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_GAINED, 55, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("close_hero_routes", "Close the Hero Routes", "Reduce hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_REDUCED, 15, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("discourage_shining_armor", "Discourage Shining Armour", "Reduce hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_REDUCED, 25, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("quiet_hero_rumours", "Quiet the Heroic Rumours", "Reduce hero influence by a total of {target}.", WeeklyMetric.HERO_INFLUENCE_REDUCED, 40, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("villain_open_house", "Villain Open House", "Increase villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_GAINED, 20, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("questionable_help", "Recruit Questionable Help", "Increase villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_GAINED, 30, 2, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("dark_reputation", "Improve the Dark Reputation", "Increase villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_GAINED, 40, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("ominous_company", "Court Ominous Company", "Increase villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_GAINED, 55, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("evict_unruly_villains", "Evict the Unruly Villains", "Reduce villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_REDUCED, 15, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("trim_villain_roster", "Trim the Villain Roster", "Reduce villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_REDUCED, 25, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("calm_lower_halls", "Calm the Lower Halls", "Reduce villain influence by a total of {target}.", WeeklyMetric.VILLAIN_INFLUENCE_REDUCED, 40, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("walls_upright", "Keep the Walls Upright", "Restore a total of {target} dungeon stability.", WeeklyMetric.STABILITY_GAINED, 15, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("brace_foundations", "Brace the Foundations", "Restore a total of {target} dungeon stability.", WeeklyMetric.STABILITY_GAINED, 25, 2, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("repair_reality", "Repair the Local Reality", "Restore a total of {target} dungeon stability.", WeeklyMetric.STABILITY_GAINED, 35, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("settle_moving_stones", "Convince the Stones to Stay Put", "Restore a total of {target} dungeon stability.", WeeklyMetric.STABILITY_GAINED, 50, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("inspect_unknown", "Inspect the Unknown", "Find {target} discoveries during exploration.", WeeklyMetric.DISCOVERIES_FOUND, 4, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("catalogue_oddities", "Catalogue the Oddities", "Find {target} discoveries during exploration.", WeeklyMetric.DISCOVERIES_FOUND, 6, 2, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("investigate_whispers", "Investigate the Whispers", "Find {target} discoveries during exploration.", WeeklyMetric.DISCOVERIES_FOUND, 9, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("buried_business", "Uncover Buried Business", "Find {target} discoveries during exploration.", WeeklyMetric.DISCOVERIES_FOUND, 12, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("no_repeat_findings", "No Repeat Findings", "Find {target} different discoveries during exploration.", WeeklyMetric.UNIQUE_DISCOVERIES_FOUND, 2, 1, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("broaden_archive", "Broaden the Archive", "Find {target} different discoveries during exploration.", WeeklyMetric.UNIQUE_DISCOVERIES_FOUND, 4, 3, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("fill_blank_shelves", "Fill the Blank Shelves", "Find {target} different discoveries during exploration.", WeeklyMetric.UNIQUE_DISCOVERIES_FOUND, 6, 5, ObjectiveMode.EXPLORE),
    ObjectiveTemplate("polite_hero_management", "Polite Hero Management", "Defeat {target} attackers while defending the dungeon.", WeeklyMetric.DEFENSE_KILLS, 20, 1, ObjectiveMode.DEFEND),
    ObjectiveTemplate("hold_front_gate", "Hold the Front Gate", "Defeat {target} attackers while defending the dungeon.", WeeklyMetric.DEFENSE_KILLS, 35, 2, ObjectiveMode.DEFEND),
    ObjectiveTemplate("graveyard_shift", "Work the Graveyard Shift", "Defeat {target} attackers while defending the dungeon.", WeeklyMetric.DEFENSE_KILLS, 50, 3, ObjectiveMode.DEFEND),
    ObjectiveTemplate("reduce_invasion_queue", "Reduce the Invasion Queue", "Defeat {target} attackers while defending the dungeon.", WeeklyMetric.DEFENSE_KILLS, 70, 4, ObjectiveMode.DEFEND),
    ObjectiveTemplate("send_heroes_home", "Send Them Home in Pieces", "Defeat {target} attackers while defending the dungeon.", WeeklyMetric.DEFENSE_KILLS, 90, 5, ObjectiveMode.DEFEND),
    ObjectiveTemplate("battlefield_salvage", "Battlefield Salvage", "Earn {target} gold while defending the dungeon.", WeeklyMetric.DEFENSE_GOLD, 1000, 1, ObjectiveMode.DEFEND, 50),
    ObjectiveTemplate("hazard_pay", "Collect the Hazard Pay", "Earn {target} gold while defending the dungeon.", WeeklyMetric.DEFENSE_GOLD, 1750, 3, ObjectiveMode.DEFEND, 50),
    ObjectiveTemplate("collect_after_battle", "Collect After the Battle", "Earn {target} gold while defending the dungeon.", WeeklyMetric.DEFENSE_GOLD, 2500, 5, ObjectiveMode.DEFEND, 50),
    ObjectiveTemplate("lessons_under_fire", "Lessons Under Fire", "Earn {target} combat XP while defending the dungeon.", WeeklyMetric.DEFENSE_XP, 250, 1, ObjectiveMode.DEFEND, 10),
    ObjectiveTemplate("train_watch", "Train the Dungeon Watch", "Earn {target} combat XP while defending the dungeon.", WeeklyMetric.DEFENSE_XP, 400, 3, ObjectiveMode.DEFEND, 10),
    ObjectiveTemplate("veteran_shift", "Complete a Veteran Shift", "Earn {target} combat XP while defending the dungeon.", WeeklyMetric.DEFENSE_XP, 600, 5, ObjectiveMode.DEFEND, 10),
)

TEMPLATES_BY_KEY = {template.key: template for template in OBJECTIVE_TEMPLATES}
LEGACY_METRIC_MAP = {
    "explorations": WeeklyMetric.EXPLORATIONS.value,
    "gold": WeeklyMetric.TOTAL_GOLD.value,
    "rooms": WeeklyMetric.UNIQUE_DISCOVERIES_FOUND.value,
    "stability": WeeklyMetric.STABILITY_GAINED.value,
    "heroes": WeeklyMetric.EXPLORATIONS.value,
}


class WeeklyObjectiveService:
    def __init__(
        self,
        *,
        players: PlayerService | None = None,
        equipment: EquipmentService | None = None,
    ) -> None:
        self.players = players or PlayerService()
        self.equipment = equipment or EquipmentService()

    def get_active(self, session: Session, *, guild_id: int, rng: random.Random | None = None) -> WeeklyObjective:
        now = utc_now()
        objective = session.scalar(
            select(WeeklyObjective)
            .where(WeeklyObjective.guild_id == guild_id, WeeklyObjective.resolved_at.is_(None))
            .order_by(WeeklyObjective.starts_at.desc(), WeeklyObjective.id.desc())
            .with_for_update()
        )
        if objective and is_before_or_equal(objective.ends_at, now):
            self.resolve_if_due(session, objective, now=now)
            objective = None
        if objective is None:
            objective = self.create_next(session, guild_id=guild_id, now=now, rng=rng)
        return objective

    def create_next(self, session: Session, *, guild_id: int, now=None, rng: random.Random | None = None) -> WeeklyObjective:
        now = ensure_utc(now or utc_now())
        dungeon = self.players.get_or_create_guild(session, guild_id=guild_id)
        self._resolve_overdue_active(session, guild_id=guild_id, now=now)
        active = session.scalar(
            select(WeeklyObjective)
            .where(WeeklyObjective.guild_id == guild_id, WeeklyObjective.resolved_at.is_(None))
            .order_by(WeeklyObjective.starts_at.desc(), WeeklyObjective.id.desc())
        )
        if active is not None:
            return active

        previous_participants = self._previous_participant_count(session, guild_id=guild_id, now=now)
        difficulty = float(dungeon.weekly_difficulty_index or INITIAL_DIFFICULTY_INDEX)
        template = self.select_template(session, guild_id=guild_id, rng=rng)
        participant_factor = max(1, previous_participants) ** PARTICIPANT_EXPONENT
        raw_target = template.base_target * participant_factor * difficulty
        rounded_target = round_target(
            raw_target,
            metric=template.metric,
            round_to=template.round_to,
            minimum=template.base_target * MIN_DIFFICULTY_INDEX,
        )
        objective = WeeklyObjective(
            guild_id=guild_id,
            objective_key=template.key,
            title=template.title,
            description=render_description(template.description_template, target=rounded_target),
            target_value=rounded_target,
            progress_value=0,
            reward_gold=0,
            starts_at=now,
            ends_at=now + OBJECTIVE_DURATION,
            metric=template.metric.value,
            mode=template.mode.value,
            effort_tier=template.effort_tier,
            difficulty_index=difficulty,
            previous_participant_count=previous_participants,
            participant_factor=participant_factor,
            raw_target_value=raw_target,
            rounded_target_value=rounded_target,
            schema_version=WEEKLY_OBJECTIVE_SCHEMA_VERSION,
            reward_policy_version=WEEKLY_REWARD_POLICY_VERSION,
        )
        session.add(objective)
        session.flush()
        return objective

    def select_template(self, session: Session, *, guild_id: int, rng: random.Random | None = None) -> ObjectiveTemplate:
        rng = rng or random
        recent = session.scalars(
            select(WeeklyObjective)
            .where(WeeklyObjective.guild_id == guild_id, WeeklyObjective.resolved_at.is_not(None))
            .order_by(desc(WeeklyObjective.resolved_at), desc(WeeklyObjective.id))
            .limit(RECENT_TEMPLATE_COOLDOWN)
        ).all()
        candidates = list(OBJECTIVE_TEMPLATES)
        recent_keys = {objective.objective_key for objective in recent[:RECENT_TEMPLATE_COOLDOWN]}
        filtered = [template for template in candidates if template.key not in recent_keys]
        candidates = filtered or candidates

        recent_metrics = {objective.metric for objective in recent[:RECENT_METRIC_COOLDOWN]}
        filtered = [template for template in candidates if template.metric.value not in recent_metrics]
        if filtered:
            candidates = filtered

        if len(recent) >= 2 and recent[0].mode == recent[1].mode:
            repeated_mode = recent[0].mode
            filtered = [template for template in candidates if template.mode.value != repeated_mode]
            if filtered:
                candidates = filtered

        recent_modes = [objective.mode for objective in recent[:3]]
        weights = []
        for template in candidates:
            weight = 1.0
            if template.mode == ObjectiveMode.DEFEND:
                weight = 2.25
                if ObjectiveMode.DEFEND.value not in recent_modes:
                    weight *= 2.0
            elif template.mode == ObjectiveMode.MIXED:
                weight = 1.4
            weights.append(weight)
        return rng.choices(candidates, weights=weights, k=1)[0]

    def record_weekly_metric(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        metric: WeeklyMetric | str,
        amount: int,
        event_id: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        amount = int(amount)
        if amount <= 0:
            return
        if not event_id:
            raise ValueError("Weekly objective events require a stable event_id")
        metric_value = _metric_value(metric)
        objective = self.get_active(session, guild_id=guild_id)
        if _objective_metric(objective) != metric_value:
            return
        player = session.scalar(select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id).with_for_update())
        if player is None:
            return
        if session.scalar(
            select(WeeklyObjectiveEvent.id).where(
                WeeklyObjectiveEvent.weekly_objective_id == objective.id,
                WeeklyObjectiveEvent.event_id == event_id,
            )
        ):
            return
        unique_key = None
        if metadata:
            raw_unique = metadata.get("unique_key") or metadata.get("discovery_key")
            unique_key = str(raw_unique) if raw_unique else None
        if metric_value == WeeklyMetric.UNIQUE_DISCOVERIES_FOUND.value:
            if not unique_key:
                return
            if session.scalar(
                select(WeeklyObjectiveEvent.id).where(
                    WeeklyObjectiveEvent.weekly_objective_id == objective.id,
                    WeeklyObjectiveEvent.metric == metric_value,
                    WeeklyObjectiveEvent.unique_key == unique_key,
                )
            ):
                return

        event = WeeklyObjectiveEvent(
            weekly_objective_id=objective.id,
            guild_id=guild_id,
            player_id=player.id,
            metric=metric_value,
            amount=amount,
            event_id=event_id,
            source=source,
            unique_key=unique_key,
            metadata_json=json.dumps(metadata or {}, sort_keys=True),
        )
        session.add(event)
        contribution = self._contribution_for(session, objective=objective, player=player)
        contribution.contribution_value += amount
        objective.progress_value += amount
        self.resolve_if_due(session, objective)

    def record_exploration_result(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        event_id: str,
        gold: int,
        xp: int,
        hero_delta: int,
        villain_delta: int,
        stability_delta: int,
        discovery_key: str | None,
        new_discovery: bool,
    ) -> None:
        active_metric = _objective_metric(self.get_active(session, guild_id=guild_id))
        events: list[tuple[WeeklyMetric, int, str, dict[str, Any] | None]] = [
            (WeeklyMetric.EXPLORATIONS, 1, "exploration", None),
            (WeeklyMetric.EXPLORE_GOLD, gold, "exploration_gold", None),
            (WeeklyMetric.TOTAL_GOLD, gold, "exploration_total_gold", None),
            (WeeklyMetric.EXPLORE_XP, xp, "exploration_xp", None),
            (WeeklyMetric.TOTAL_XP, xp, "exploration_total_xp", None),
        ]
        if hero_delta > 0:
            events.append((WeeklyMetric.HERO_INFLUENCE_GAINED, hero_delta, "hero_gain", None))
        elif hero_delta < 0:
            events.append((WeeklyMetric.HERO_INFLUENCE_REDUCED, abs(hero_delta), "hero_reduce", None))
        if villain_delta > 0:
            events.append((WeeklyMetric.VILLAIN_INFLUENCE_GAINED, villain_delta, "villain_gain", None))
        elif villain_delta < 0:
            events.append((WeeklyMetric.VILLAIN_INFLUENCE_REDUCED, abs(villain_delta), "villain_reduce", None))
        if stability_delta > 0:
            events.append((WeeklyMetric.STABILITY_GAINED, stability_delta, "stability_gain", None))
        if discovery_key:
            events.append((WeeklyMetric.DISCOVERIES_FOUND, 1, "discovery", {"discovery_key": discovery_key}))
            if new_discovery:
                events.append((WeeklyMetric.UNIQUE_DISCOVERIES_FOUND, 1, "unique_discovery", {"discovery_key": discovery_key}))
        for metric, amount, suffix, metadata in events:
            if metric.value != active_metric:
                continue
            self.record_weekly_metric(
                session,
                guild_id=guild_id,
                user_id=user_id,
                metric=metric,
                amount=amount,
                event_id=f"{event_id}:{suffix}",
                source="exploration",
                metadata=metadata,
            )

    def record_defense_result(self, session: Session, *, guild_id: int, user_id: int, report) -> None:
        event_id = f"defense:{report.session_id}"
        active_metric = _objective_metric(self.get_active(session, guild_id=guild_id))
        for metric, amount, suffix in (
            (WeeklyMetric.DEFENSE_KILLS, report.victories, "kills"),
            (WeeklyMetric.DEFENSE_GOLD, report.gold_earned, "gold"),
            (WeeklyMetric.TOTAL_GOLD, report.gold_earned, "total_gold"),
            (WeeklyMetric.DEFENSE_XP, report.combat_xp_earned, "xp"),
            (WeeklyMetric.TOTAL_XP, report.combat_xp_earned, "total_xp"),
        ):
            if metric.value != active_metric:
                continue
            self.record_weekly_metric(
                session,
                guild_id=guild_id,
                user_id=user_id,
                metric=metric,
                amount=amount,
                event_id=f"{event_id}:{suffix}",
                source="defense",
                metadata={"defense_session_id": report.session_id},
            )

    def add_progress(
        self,
        session: Session,
        *,
        guild_id: int,
        player: Player,
        amount: int,
        key_hint: str | None = None,
    ) -> None:
        if amount <= 0:
            return
        objective = self.get_active(session, guild_id=guild_id)
        contribution = self._contribution_for(session, objective=objective, player=player)
        contribution.contribution_value += int(amount)
        objective.progress_value += int(amount)
        self.resolve_if_due(session, objective)

    def resolve_if_due(self, session: Session, objective: WeeklyObjective, *, now=None) -> bool:
        now = ensure_utc(now or utc_now())
        if objective.resolved_at is not None:
            return False
        target = max(1, int(objective.target_value))
        if objective.progress_value >= target:
            self._resolve(session, objective, succeeded=True, now=now)
            return True
        if is_before_or_equal(objective.ends_at, now):
            self._resolve(session, objective, succeeded=False, now=now)
            return True
        return False

    def contribution_rows(self, session: Session, objective: WeeklyObjective, *, limit: int = 10):
        return session.execute(
            select(Player.display_name, WeeklyPlayerContribution.contribution_value)
            .join(Player, Player.id == WeeklyPlayerContribution.player_id)
            .where(WeeklyPlayerContribution.weekly_objective_id == objective.id)
            .order_by(desc(WeeklyPlayerContribution.contribution_value))
            .limit(limit)
        ).all()

    def player_contribution(self, session: Session, objective: WeeklyObjective, *, player_id: int | None) -> int:
        if player_id is None:
            return 0
        return int(
            session.scalar(
                select(WeeklyPlayerContribution.contribution_value).where(
                    WeeklyPlayerContribution.weekly_objective_id == objective.id,
                    WeeklyPlayerContribution.player_id == player_id,
                )
            )
            or 0
        )

    def qualifies_for_reward(self, objective: WeeklyObjective, contribution: int) -> bool:
        return contribution >= minimum_required_contribution(objective)

    def reward_preview(self, player: Player, objective: WeeklyObjective) -> WeeklyRewardPreview:
        return calculate_reward_preview(
            player.explore_level,
            effort_tier=int(objective.effort_tier or 1),
            difficulty_index=float(objective.difficulty_index or 1.0),
            equipment=self.equipment,
        )

    def _resolve(self, session: Session, objective: WeeklyObjective, *, succeeded: bool, now) -> None:
        objective.resolved_at = now
        objective.succeeded = succeeded
        objective.participant_count = self._participant_count(session, objective)
        dungeon = self.players.get_or_create_guild(session, guild_id=objective.guild_id)
        current = float(dungeon.weekly_difficulty_index or INITIAL_DIFFICULTY_INDEX)
        if succeeded:
            dungeon.weekly_difficulty_index = min(MAX_DIFFICULTY_INDEX, current * SUCCESS_DIFFICULTY_MULTIPLIER)
            self.process_rewards(session, objective, now=now)
        else:
            dungeon.weekly_difficulty_index = max(MIN_DIFFICULTY_INDEX, current * FAILURE_DIFFICULTY_MULTIPLIER)

    def process_rewards(self, session: Session, objective: WeeklyObjective, *, now=None) -> None:
        now = ensure_utc(now or utc_now())
        if objective.succeeded is not True:
            return
        minimum = minimum_required_contribution(objective)
        rows = session.execute(
            select(WeeklyPlayerContribution, Player)
            .join(Player, Player.id == WeeklyPlayerContribution.player_id)
            .where(WeeklyPlayerContribution.weekly_objective_id == objective.id)
        ).all()
        eligible_count = 0
        total_paid = 0
        for contribution, player in rows:
            if contribution.contribution_value < minimum:
                continue
            existing = session.scalar(
                select(WeeklyObjectiveReward).where(
                    WeeklyObjectiveReward.objective_id == objective.id,
                    WeeklyObjectiveReward.user_id == player.id,
                )
            )
            if existing is not None:
                continue
            preview = self.reward_preview(player, objective)
            player.gold += preview.gold_awarded
            session.add(
                WeeklyObjectiveReward(
                    objective_id=objective.id,
                    guild_id=objective.guild_id,
                    user_id=player.id,
                    explore_level_used=preview.explore_level_used,
                    reference_equipment_cost=preview.reference_equipment_cost,
                    effort_multiplier=preview.effort_multiplier,
                    difficulty_multiplier=preview.difficulty_multiplier,
                    contribution=contribution.contribution_value,
                    minimum_required_contribution=minimum,
                    gold_awarded=preview.gold_awarded,
                    awarded_at=now,
                )
            )
            eligible_count += 1
            total_paid += preview.gold_awarded
        objective.rewards_granted_at = now
        log.info(
            "Processed weekly objective rewards",
            extra={
                "objective_id": objective.id,
                "guild_id": objective.guild_id,
                "eligible_count": eligible_count,
                "total_paid": total_paid,
            },
        )

    def _resolve_overdue_active(self, session: Session, *, guild_id: int, now) -> None:
        objective = session.scalar(
            select(WeeklyObjective)
            .where(WeeklyObjective.guild_id == guild_id, WeeklyObjective.resolved_at.is_(None))
            .order_by(WeeklyObjective.starts_at.desc(), WeeklyObjective.id.desc())
            .with_for_update()
        )
        if objective is not None and is_before_or_equal(objective.ends_at, now):
            self.resolve_if_due(session, objective, now=now)

    def _previous_participant_count(self, session: Session, *, guild_id: int, now) -> int:
        previous = session.scalar(
            select(WeeklyObjective)
            .where(WeeklyObjective.guild_id == guild_id, WeeklyObjective.resolved_at.is_not(None))
            .order_by(desc(WeeklyObjective.resolved_at), desc(WeeklyObjective.id))
        )
        if previous is not None:
            count = int(previous.participant_count or 0) or self._participant_count(session, previous)
            return max(1, count)
        since = ensure_utc(now) - OBJECTIVE_DURATION
        active_players = int(
            session.scalar(
                select(func.count(Player.id)).where(
                    Player.guild_id == guild_id,
                    Player.last_exploration_at.is_not(None),
                    Player.last_exploration_at >= since,
                )
            )
            or 0
        )
        return max(1, active_players)

    def _participant_count(self, session: Session, objective: WeeklyObjective) -> int:
        return int(
            session.scalar(
                select(func.count(WeeklyPlayerContribution.id)).where(
                    WeeklyPlayerContribution.weekly_objective_id == objective.id,
                    WeeklyPlayerContribution.contribution_value > 0,
                )
            )
            or 0
        )

    def _contribution_for(self, session: Session, *, objective: WeeklyObjective, player: Player) -> WeeklyPlayerContribution:
        contribution = session.scalar(
            select(WeeklyPlayerContribution)
            .where(
                WeeklyPlayerContribution.weekly_objective_id == objective.id,
                WeeklyPlayerContribution.player_id == player.id,
            )
            .with_for_update()
        )
        if contribution is None:
            contribution = WeeklyPlayerContribution(
                weekly_objective_id=objective.id,
                player_id=player.id,
                contribution_value=0,
            )
            session.add(contribution)
            session.flush()
        return contribution


def render_description(template: str, **values: Any) -> str:
    fields = {field_name for _, field_name, _, _ in string.Formatter().parse(template) if field_name}
    unknown = fields - values.keys()
    missing_target = "target" not in fields
    if missing_target or unknown:
        raise ValueError(f"Invalid weekly objective description tokens: {sorted(unknown)}")
    return template.format(**{key: _format_target(value) for key, value in values.items()})


def round_target(raw_target: float, *, metric: WeeklyMetric, round_to: int, minimum: float) -> int:
    round_to = _metric_round_to(metric, round_to)
    target = int(round(raw_target / round_to) * round_to)
    minimum_target = int(math.ceil(max(1.0, minimum) / round_to) * round_to)
    return max(round_to, minimum_target, target)


def minimum_required_contribution(objective: WeeklyObjective) -> int:
    expected_share = objective.target_value / max(1, int(objective.previous_participant_count or 1))
    raw = expected_share * 0.01
    metric = WeeklyMetric(_objective_metric(objective))
    if metric in {WeeklyMetric.EXPLORE_GOLD, WeeklyMetric.TOTAL_GOLD, WeeklyMetric.DEFENSE_GOLD}:
        return max(10, int(math.ceil(raw / 10) * 10))
    if metric in {WeeklyMetric.EXPLORE_XP, WeeklyMetric.TOTAL_XP, WeeklyMetric.DEFENSE_XP}:
        return max(5, int(math.ceil(raw / 5) * 5))
    return max(1, int(math.ceil(raw)))


def calculate_reward_preview(
    explore_level: int,
    *,
    effort_tier: int,
    difficulty_index: float,
    equipment: EquipmentService | None = None,
) -> WeeklyRewardPreview:
    equipment = equipment or EquipmentService()
    reference_cost = reference_equipment_cost(explore_level, equipment=equipment)
    base_reward = max(200.0, reference_cost * 0.35)
    effort_multiplier = EFFORT_MULTIPLIERS[effort_tier]
    difficulty_multiplier = max(0.90, min(1.20, difficulty_index**0.20))
    cap = max(200.0, reference_cost * 0.60)
    raw_reward = min(cap, base_reward * effort_multiplier * difficulty_multiplier)
    reward = int(round(raw_reward / 5) * 5)
    return WeeklyRewardPreview(
        explore_level_used=max(1, int(explore_level)),
        reference_equipment_cost=int(reference_cost),
        effort_multiplier=effort_multiplier,
        difficulty_multiplier=difficulty_multiplier,
        gold_awarded=max(5, reward),
    )


def reference_equipment_cost(explore_level: int, *, equipment: EquipmentService | None = None) -> int:
    equipment = equipment or EquipmentService()
    level = max(1, int(explore_level))
    exact = [item.cost for item in equipment.items if item.min_level <= level <= item.max_level]
    if exact:
        return int(median(exact))
    lower = _closest_lower_band(level, equipment.items)
    if lower:
        log.warning("Using lower equipment reward fallback", extra={"explore_level": level})
        return int(median(item.cost for item in lower))
    higher = _closest_higher_band(level, equipment.items)
    if higher:
        log.warning("Using higher equipment reward fallback", extra={"explore_level": level})
        return int(median(item.cost for item in higher))
    raise ValueError("No equipment content available for weekly reward reference")


def _closest_lower_band(level: int, items: list[EquipmentItem]) -> list[EquipmentItem]:
    lower_max = max((item.max_level for item in items if item.max_level < level), default=None)
    if lower_max is None:
        return []
    return [item for item in items if item.max_level == lower_max]


def _closest_higher_band(level: int, items: list[EquipmentItem]) -> list[EquipmentItem]:
    higher_min = min((item.min_level for item in items if item.min_level > level), default=None)
    if higher_min is None:
        return []
    return [item for item in items if item.min_level == higher_min]


def _format_target(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _metric_round_to(metric: WeeklyMetric, template_round_to: int) -> int:
    if metric in {WeeklyMetric.EXPLORE_GOLD, WeeklyMetric.TOTAL_GOLD, WeeklyMetric.DEFENSE_GOLD}:
        return 50
    if metric in {WeeklyMetric.EXPLORE_XP, WeeklyMetric.TOTAL_XP, WeeklyMetric.DEFENSE_XP}:
        return 10
    return max(1, template_round_to)


def _metric_value(metric: WeeklyMetric | str) -> str:
    return metric.value if isinstance(metric, WeeklyMetric) else str(metric)


def _objective_metric(objective: WeeklyObjective) -> str:
    if objective.schema_version >= WEEKLY_OBJECTIVE_SCHEMA_VERSION:
        return objective.metric
    return LEGACY_METRIC_MAP.get(objective.objective_key, objective.metric or WeeklyMetric.EXPLORATIONS.value)
