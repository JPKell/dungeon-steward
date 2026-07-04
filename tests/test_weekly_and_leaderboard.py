from __future__ import annotations

from datetime import timedelta

from sqlalchemy import desc, select

from bot.models import Player
from bot.services.weekly_objective_service import WeeklyObjectiveService
from tests.conftest import make_player


def test_weekly_progress_updates_and_resolves_once(db, now):
    service = WeeklyObjectiveService()
    objective = service.create_next(db, guild_id=10, now=now)
    objective.target_value = 2
    player = make_player(db, now=now, guild_id=10)
    service.add_progress(db, guild_id=10, player=player, amount=1)
    assert objective.resolved_at is None
    service.add_progress(db, guild_id=10, player=player, amount=1)
    first_resolved = objective.resolved_at
    assert first_resolved is not None
    assert service.resolve_if_due(db, objective) is False
    assert objective.resolved_at == first_resolved


def test_overdue_objective_resolves_after_downtime(db, now):
    service = WeeklyObjectiveService()
    objective = service.create_next(db, guild_id=10, now=now - timedelta(days=8))
    objective.ends_at = now - timedelta(days=1)
    db.flush()
    active = service.get_active(db, guild_id=10)
    assert objective.resolved_at is not None
    assert active.id != objective.id


def test_guild_leaderboard_excludes_other_servers(db, now):
    player_a = make_player(db, now=now, user_id=1, guild_id=10)
    player_a.experience = 100
    player_b = make_player(db, now=now, user_id=2, guild_id=20)
    player_b.experience = 999
    rows = db.execute(
        select(Player.display_name, Player.experience)
        .where(Player.guild_id == 10, Player.is_active.is_(True))
        .order_by(desc(Player.experience))
        .limit(10)
    ).all()
    assert rows == [(player_a.display_name, 100)]
