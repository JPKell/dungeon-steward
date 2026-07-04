from __future__ import annotations

from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService


def main() -> None:
    encounters = EncounterService().encounters
    discoveries = DiscoveryService().load_content()
    discovery_keys = {item["key"] for item in discoveries}
    missing = sorted(
        {
            choice.discovery_key
            for encounter in encounters
            for choice in encounter.choices
            if choice.discovery_key and choice.discovery_key not in discovery_keys
        }
    )
    if missing:
        raise SystemExit(f"Unknown discovery keys in encounters: {', '.join(missing)}")
    print(f"Validated {len(encounters)} encounters and {len(discoveries)} discoveries.")


if __name__ == "__main__":
    main()

