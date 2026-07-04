from __future__ import annotations

from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService


def test_encounter_content_is_valid():
    encounters = EncounterService().encounters
    assert len(encounters) >= 20
    assert all(2 <= len(encounter.choices) <= 4 for encounter in encounters)


def test_discovery_content_is_valid():
    discoveries = DiscoveryService().load_content()
    assert len(discoveries) >= 15

