from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.config import EXPLORATION_TIMEOUT_SECONDS
from bot.models import EncounterHistory, ExplorationSession, Player
from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import Choice, Encounter, EncounterService
from bot.services.energy_service import EnergyService, EnergyState
from bot.services.guild_dungeon_service import GuildDungeonService
from bot.services.player_service import PlayerService
from bot.services.progression_service import (
    calculate_explore_level,
    scale_exploration_gold,
    scale_exploration_xp,
)
from bot.services.weekly_objective_service import WeeklyObjectiveService
from bot.utils.time import ensure_utc, is_before_or_equal, utc_now


class ExplorationError(Exception):
    pass


class ExplorationAlreadyResolvedError(ExplorationError):
    pass


class ExplorationExpiredError(ExplorationError):
    pass


class ExplorationNotOwnedError(ExplorationError):
    pass


@dataclass(frozen=True)
class StartedExploration:
    session: ExplorationSession
    encounter: Encounter
    energy_state: EnergyState


@dataclass(frozen=True)
class ResolvedExploration:
    session: ExplorationSession
    encounter: Encounter
    choice: Choice
    gold: int
    experience: int
    leveled_up: bool
    discovery_name: str | None
    new_discovery: bool
    energy_state: EnergyState


class ExplorationService:
    def __init__(
        self,
        *,
        encounters: EncounterService | None = None,
        energy: EnergyService | None = None,
        players: PlayerService | None = None,
        discoveries: DiscoveryService | None = None,
        guilds: GuildDungeonService | None = None,
        weekly: WeeklyObjectiveService | None = None,
    ) -> None:
        self.encounters = encounters or EncounterService()
        self.energy = energy or EnergyService()
        self.players = players or PlayerService()
        self.discoveries = discoveries or DiscoveryService()
        self.guilds = guilds or GuildDungeonService()
        self.weekly = weekly or WeeklyObjectiveService()

    def start(
        self,
        session: Session,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        now: datetime | None = None,
    ) -> StartedExploration:
        now = ensure_utc(now or utc_now())
        player = self.players.get_or_create(
            session, guild_id=guild_id, user_id=user_id, display_name=display_name
        )
        self.players.get_or_create_guild(session, guild_id=guild_id)
        energy_state = self.energy.spend(player, now=now)
        encounter = self.encounters.select(explore_level=player.explore_level)
        exploration = ExplorationSession(
            resolution_key=secrets.token_urlsafe(24),
            player_id=player.id,
            guild_id=guild_id,
            encounter_key=encounter.key,
            expires_at=now + timedelta(seconds=EXPLORATION_TIMEOUT_SECONDS),
        )
        session.add(exploration)
        session.flush()
        return StartedExploration(exploration, encounter, energy_state)

    def resolve(
        self,
        session: Session,
        *,
        resolution_key: str,
        choice_key: str,
        acting_user_id: int,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> ResolvedExploration:
        now = ensure_utc(now or utc_now())
        rng = rng or random
        exploration = session.scalar(
            select(ExplorationSession).where(ExplorationSession.resolution_key == resolution_key)
        )
        if exploration is None:
            raise ExplorationExpiredError("Exploration session was not found")
        player = session.get(Player, exploration.player_id)
        if player is None or player.discord_user_id != acting_user_id:
            raise ExplorationNotOwnedError
        if exploration.resolved_at is not None:
            raise ExplorationAlreadyResolvedError
        if is_before_or_equal(exploration.expires_at, now):
            exploration.expired_at = now
            raise ExplorationExpiredError

        encounter = self.encounters.get(exploration.encounter_key)
        choice = next((candidate for candidate in encounter.choices if candidate.key == choice_key), None)
        if choice is None:
            raise ExplorationError("Invalid choice")

        reward_explore_level = player.explore_level
        base_gold = rng.randint(choice.gold_min, choice.gold_max)
        base_experience = rng.randint(choice.xp_min, choice.xp_max)
        gold = scale_exploration_gold(base_gold, reward_explore_level)
        experience = scale_exploration_xp(base_experience, reward_explore_level)
        exploration.selected_choice_key = choice.key
        exploration.resolved_at = now
        player.gold += gold
        player.experience += experience
        player.hero_influence += choice.hero_effect
        player.villain_influence += choice.villain_effect
        player.total_explorations += 1
        player.last_exploration_at = now
        if choice.success:
            player.successful_explorations += 1
        else:
            player.failed_explorations += 1
        old_explore_level = player.explore_level
        player.explore_level = calculate_explore_level(player.experience)

        discovery, is_new = self.discoveries.award(session, player, choice.discovery_key)
        dungeon = self.players.get_or_create_guild(session, guild_id=exploration.guild_id)
        self.guilds.apply_choice(
            dungeon,
            gold=gold,
            hero_effect=choice.hero_effect,
            villain_effect=choice.villain_effect,
            stability_effect=choice.stability_effect,
            discovery_category=discovery.category if discovery else None,
        )
        self.weekly.add_progress(
            session,
            guild_id=exploration.guild_id,
            player=player,
            amount=choice.weekly_progress,
        )
        session.add(
            EncounterHistory(
                exploration_session_id=exploration.id,
                player_id=player.id,
                encounter_key=encounter.key,
                choice_key=choice.key,
                gold_awarded=gold,
                experience_awarded=experience,
                discovery_key=choice.discovery_key,
            )
        )
        return ResolvedExploration(
            session=exploration,
            encounter=encounter,
            choice=choice,
            gold=gold,
            experience=experience,
            leveled_up=player.explore_level > old_explore_level,
            discovery_name=discovery.name if discovery else None,
            new_discovery=is_new,
            energy_state=self.energy.state(player, now=now),
        )
