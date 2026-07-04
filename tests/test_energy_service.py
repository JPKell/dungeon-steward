from __future__ import annotations

from datetime import timedelta

import pytest

from bot.config import MAX_ENERGY
from bot.services.energy_service import EnergyService, InsufficientEnergyError
from bot.services.player_service import PlayerService
from tests.conftest import make_player


def test_new_players_start_full(db):
    player = PlayerService().get_or_create(db, guild_id=1, user_id=1, display_name="A")
    assert player.energy == MAX_ENERGY


def test_no_elapsed_time(db, now):
    player = make_player(db, now=now)
    player.energy = 4
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == 4


def test_less_than_two_hours_preserves_partial(db, now):
    player = make_player(db, now=now - timedelta(hours=1, minutes=30))
    player.energy = 4
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == 4
    assert state.seconds_until_next == 30 * 60


def test_exactly_two_hours_regenerates(db, now):
    player = make_player(db, now=now - timedelta(hours=2))
    player.energy = 4
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == 5
    assert state.seconds_until_next == 2 * 60 * 60


def test_several_intervals_and_partial_preserved(db, now):
    player = make_player(db, now=now - timedelta(hours=7, minutes=15))
    player.energy = 2
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == 5
    assert state.seconds_until_next == 45 * 60


def test_more_than_24_hours_caps(db, now):
    player = make_player(db, now=now - timedelta(days=5))
    player.energy = 0
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == MAX_ENERGY
    assert player.energy_updated_at == now


def test_player_already_at_max_resets_reference(db, now):
    player = make_player(db, now=now - timedelta(days=3))
    player.energy = MAX_ENERGY
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == MAX_ENERGY
    assert player.energy_updated_at == now


def test_spending_energy_while_at_max_does_not_bank_days(db, now):
    player = make_player(db, now=now - timedelta(days=3))
    player.energy = MAX_ENERGY
    state = EnergyService().spend(player, now=now)
    assert state.energy == MAX_ENERGY - 1
    assert player.energy_updated_at == now


def test_offline_for_days_regenerates_to_cap(db, now):
    player = make_player(db, now=now - timedelta(days=12))
    player.energy = 1
    assert EnergyService().recalculate(player, now=now).energy == MAX_ENERGY


def test_energy_cannot_become_negative(db, now):
    player = make_player(db, now=now)
    player.energy = 0
    with pytest.raises(InsufficientEnergyError):
        EnergyService().spend(player, now=now)
    assert player.energy == 0


def test_concurrent_spending_cannot_exceed_available_energy(db, now):
    player = make_player(db, now=now)
    player.energy = 1
    service = EnergyService()
    service.spend(player, now=now)
    with pytest.raises(InsufficientEnergyError):
        service.spend(player, now=now)
