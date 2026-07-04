from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import Player, WeeklyObjective, WeeklyPlayerContribution
from bot.utils.time import ensure_utc, is_before_or_equal, utc_now


@dataclass(frozen=True)
class ObjectiveTemplate:
    key: str
    title: str
    description: str
    target_value: int
    reward_gold: int


OBJECTIVE_TEMPLATES = [
    ObjectiveTemplate("explorations", "Map the Moving Halls", "Complete 100 explorations.", 100, 250),
    ObjectiveTemplate("gold", "Recover the Rent", "Recover 2,000 dungeon gold.", 2000, 300),
    ObjectiveTemplate("rooms", "Name the Nameless Rooms", "Discover 10 unique rooms.", 10, 200),
    ObjectiveTemplate("heroes", "Polite Hero Management", "Defeat or redirect 40 invading heroes.", 40, 250),
    ObjectiveTemplate("stability", "Keep the Walls Upright", "Restore dungeon stability above 70.", 70, 250),
]


class WeeklyObjectiveService:
    def get_active(self, session: Session, *, guild_id: int) -> WeeklyObjective:
        now = utc_now()
        objective = session.scalar(
            select(WeeklyObjective)
            .where(WeeklyObjective.guild_id == guild_id, WeeklyObjective.resolved_at.is_(None))
            .order_by(WeeklyObjective.starts_at.desc())
        )
        if objective:
            if is_before_or_equal(objective.ends_at, now):
                self.resolve_if_due(session, objective)
                objective = None
        if objective is None:
            objective = self.create_next(session, guild_id=guild_id, now=now)
        return objective

    def create_next(self, session: Session, *, guild_id: int, now=None) -> WeeklyObjective:
        now = ensure_utc(now or utc_now())
        template = random.choice(OBJECTIVE_TEMPLATES)
        objective = WeeklyObjective(
            guild_id=guild_id,
            objective_key=template.key,
            title=template.title,
            description=template.description,
            target_value=template.target_value,
            reward_gold=template.reward_gold,
            starts_at=now,
            ends_at=now + timedelta(days=7),
        )
        session.add(objective)
        session.flush()
        return objective

    def add_progress(
        self, session: Session, *, guild_id: int, player: Player, amount: int, key_hint: str | None = None
    ) -> None:
        objective = self.get_active(session, guild_id=guild_id)
        if key_hint and objective.objective_key not in {key_hint, "explorations"}:
            return
        objective.progress_value = min(objective.target_value, objective.progress_value + max(0, amount))
        contribution = session.scalar(
            select(WeeklyPlayerContribution).where(
                WeeklyPlayerContribution.weekly_objective_id == objective.id,
                WeeklyPlayerContribution.player_id == player.id,
            )
        )
        if contribution is None:
            contribution = WeeklyPlayerContribution(
                weekly_objective_id=objective.id,
                player_id=player.id,
                contribution_value=0,
            )
            session.add(contribution)
        contribution.contribution_value += max(0, amount)
        self.resolve_if_due(session, objective)

    def resolve_if_due(self, session: Session, objective: WeeklyObjective) -> bool:
        now = utc_now()
        if objective.resolved_at is not None:
            return False
        if objective.progress_value >= objective.target_value or is_before_or_equal(objective.ends_at, now):
            objective.resolved_at = now
            objective.rewards_granted_at = now
            return True
        return False

