from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from bot.models import EncounterHistory, ExplorationSession, Player
from bot.services.energy_service import InsufficientEnergyError
from bot.services.exploration_service import (
    ExplorationAlreadyResolvedError,
    ExplorationExpiredError,
    ExplorationNotOwnedError,
    ExplorationService,
)
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

