from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from bot.config import EXPLORATION_ENERGY_COST, MAX_ENERGY
from bot.models import Player
from bot.services.progression_service import get_explore_cooldown_minutes
from bot.utils.time import ensure_utc, utc_now


@dataclass(frozen=True)
class EnergyState:
    energy: int
    next_energy_at: datetime | None
    full_energy_at: datetime | None
    seconds_until_next: int
    seconds_until_full: int


class InsufficientEnergyError(Exception):
    pass


class EnergyService:
    def recalculate(self, player: Player, *, now: datetime | None = None) -> EnergyState:
        now = ensure_utc(now or utc_now())
        updated_at = ensure_utc(player.energy_updated_at)
        regen_seconds = _regen_seconds(player)
        player.energy = min(MAX_ENERGY, max(0, player.energy))

        if player.energy >= MAX_ENERGY:
            player.energy = MAX_ENERGY
            player.energy_updated_at = now
            return self.state(player, now=now)

        elapsed = max(0, int((now - updated_at).total_seconds()))
        intervals = elapsed // regen_seconds
        remainder = elapsed % regen_seconds

        if intervals:
            player.energy = min(MAX_ENERGY, player.energy + intervals)
            if player.energy >= MAX_ENERGY:
                player.energy = MAX_ENERGY
                player.energy_updated_at = now
            else:
                player.energy_updated_at = now - timedelta(seconds=remainder)

        return self.state(player, now=now)

    def spend(self, player: Player, *, now: datetime | None = None) -> EnergyState:
        now = ensure_utc(now or utc_now())
        state = self.recalculate(player, now=now)
        if player.energy < EXPLORATION_ENERGY_COST:
            raise InsufficientEnergyError
        player.energy -= EXPLORATION_ENERGY_COST
        if player.energy < MAX_ENERGY and state.energy >= MAX_ENERGY:
            player.energy_updated_at = now
        return self.state(player, now=now)

    def grant(self, player: Player, amount: int, *, now: datetime | None = None) -> EnergyState:
        now = ensure_utc(now or utc_now())
        self.recalculate(player, now=now)
        player.energy = min(MAX_ENERGY, max(0, player.energy + amount))
        if player.energy >= MAX_ENERGY:
            player.energy_updated_at = now
        return self.state(player, now=now)

    def set_energy(self, player: Player, amount: int, *, now: datetime | None = None) -> EnergyState:
        now = ensure_utc(now or utc_now())
        player.energy = min(MAX_ENERGY, max(0, amount))
        player.energy_updated_at = now
        return self.state(player, now=now)

    def state(self, player: Player, *, now: datetime | None = None) -> EnergyState:
        now = ensure_utc(now or utc_now())
        regen_seconds = _regen_seconds(player)
        energy = min(MAX_ENERGY, max(0, player.energy))
        if energy >= MAX_ENERGY:
            return EnergyState(energy, None, None, 0, 0)
        updated_at = ensure_utc(player.energy_updated_at)
        elapsed = max(0, int((now - updated_at).total_seconds()))
        until_next = max(0, regen_seconds - elapsed)
        missing = MAX_ENERGY - energy
        until_full = until_next + ((missing - 1) * regen_seconds)
        return EnergyState(
            energy=energy,
            next_energy_at=now + timedelta(seconds=until_next),
            full_energy_at=now + timedelta(seconds=until_full),
            seconds_until_next=until_next,
            seconds_until_full=until_full,
        )


def _regen_seconds(player: Player) -> int:
    return get_explore_cooldown_minutes(player.explore_level) * 60
