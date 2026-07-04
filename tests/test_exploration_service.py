from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from bot.models import EncounterHistory, ExplorationSession, Player
from bot.services.energy_service import InsufficientEnergyError
from bot.services.exploration_service import (
    ExplorationAlreadyResolvedError,
    ExplorationError,
    ExplorationExpiredError,
    ExplorationNotOwnedError,
    ExplorationService,
)
from bot.views.exploration import DungeonActionView
from tests.conftest import make_player


def test_exploration_consumes_one_energy(db, now):
    started = ExplorationService().start(
        db, guild_id=10, user_id=1, display_name="Scout", now=now
    )
    player = db.get(Player, started.session.player_id)
    assert player.energy == 11


def test_player_with_no_energy_cannot_explore(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.energy = 0
    db.flush()
    with pytest.raises(InsufficientEnergyError):
        ExplorationService().start(db, guild_id=10, user_id=1, display_name="Scout", now=now)


def test_another_player_cannot_resolve_buttons(db, now):
    started = ExplorationService().start(
        db, guild_id=10, user_id=1, display_name="Scout", now=now
    )
    with pytest.raises(ExplorationNotOwnedError):
        ExplorationService().resolve(
            db,
            resolution_key=started.session.resolution_key,
            choice_key=started.encounter.choices[0].key,
            acting_user_id=2,
            now=now,
        )


def test_encounter_cannot_resolve_twice(db, now):
    service = ExplorationService()
    started = service.start(db, guild_id=10, user_id=1, display_name="Scout", now=now)
    service.resolve(
        db,
        resolution_key=started.session.resolution_key,
        choice_key=started.encounter.choices[0].key,
        acting_user_id=1,
        now=now,
    )
    with pytest.raises(ExplorationAlreadyResolvedError):
        service.resolve(
            db,
            resolution_key=started.session.resolution_key,
            choice_key=started.encounter.choices[1].key,
            acting_user_id=1,
            now=now,
        )
    assert db.scalar(select(func.count()).select_from(EncounterHistory)) == 1


def test_rewards_recorded_once(db, now):
    service = ExplorationService()
    started = service.start(db, guild_id=10, user_id=1, display_name="Scout", now=now)
    service.resolve(
        db,
        resolution_key=started.session.resolution_key,
        choice_key=started.encounter.choices[0].key,
        acting_user_id=1,
        now=now,
    )
    assert db.scalar(select(func.count()).select_from(EncounterHistory)) == 1


def test_selected_dungeon_level_is_persisted(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.highest_unlocked_dungeon_level = 3
    player.highest_completed_dungeon_level = 3
    player.energy = 12
    service = ExplorationService()
    started = service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=3, now=now)

    assert started.session.dungeon_level == 3

    service.resolve(
        db,
        resolution_key=started.session.resolution_key,
        choice_key=started.encounter.choices[0].key,
        acting_user_id=1,
        now=now,
    )
    history = db.scalar(select(EncounterHistory))
    assert history is not None
    assert history.dungeon_level == 3


def test_locked_dungeon_level_rejects_before_spending_energy(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.energy = 12
    db.flush()

    with pytest.raises(ExplorationError):
        ExplorationService().start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=2, now=now)

    assert player.energy == 12


def test_expired_exploration_cannot_be_resolved(db, now):
    service = ExplorationService()
    started = service.start(db, guild_id=10, user_id=1, display_name="Scout", now=now)
    with pytest.raises(ExplorationExpiredError):
        service.resolve(
            db,
            resolution_key=started.session.resolution_key,
            choice_key=started.encounter.choices[0].key,
            acting_user_id=1,
            now=now + timedelta(minutes=6),
        )
    stored = db.get(ExplorationSession, started.session.id)
    assert stored.expired_at is not None


def test_naive_expires_at_is_treated_as_utc(db, now):
    service = ExplorationService()
    started = service.start(db, guild_id=10, user_id=1, display_name="Scout", now=now)
    started.session.expires_at = started.session.expires_at.replace(tzinfo=None)
    db.flush()

    with pytest.raises(ExplorationExpiredError):
        service.resolve(
            db,
            resolution_key=started.session.resolution_key,
            choice_key=started.encounter.choices[0].key,
            acting_user_id=1,
            now=now + timedelta(minutes=6),
        )


@pytest.mark.asyncio
async def test_explore_button_starts_exploration_directly():
    started_levels: list[tuple[object, int]] = []

    class RecordingActionView(DungeonActionView):
        async def start_exploration(self, interaction, dungeon_level: int = 1) -> None:
            started_levels.append((interaction, dungeon_level))

    view = RecordingActionView(
        session_factory=object(),
        exploration_service=object(),
        defense_service=object(),
        shop_service=object(),
        owner_user_id=1,
    )
    interaction = SimpleNamespace(guild_id=10)

    await view.show_exploration_selector(interaction)

    assert started_levels == [(interaction, 1)]
