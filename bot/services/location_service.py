from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LocationContentError(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    key: str
    name: str
    banner_asset: str | None = None


class LocationService:
    def __init__(
        self,
        content_path: Path | None = None,
        *,
        document: list[Any] | None = None,
    ) -> None:
        self.content_path = content_path or Path(__file__).parents[1] / "content" / "locations.json"
        self._document = document
        self.locations = self._load()
        self._by_key = {location.key: location for location in self.locations}

    def get(self, key: str) -> Location:
        try:
            return self._by_key[key]
        except KeyError as error:
            raise LocationContentError(f"Unknown location: {key}") from error

    def banner_asset_for(self, key: str) -> str | None:
        return self.get(key).banner_asset

    def _load(self) -> tuple[Location, ...]:
        raw = self._document
        if raw is None:
            raw = _LOCATION_DOCUMENT
        if raw is None:
            raw = json.loads(self.content_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise LocationContentError("locations.json must be a list")
        locations = tuple(_location(entry) for entry in raw)
        keys = [location.key for location in locations]
        if len(keys) != len(set(keys)):
            raise LocationContentError("Location keys must be unique")
        return locations


def _location(entry: Any) -> Location:
    if not isinstance(entry, dict):
        raise LocationContentError("Location entries must be objects")
    return Location(
        key=_required_str(entry, "key"),
        name=_required_str(entry, "name"),
        banner_asset=_optional_str(entry, "banner_asset"),
    )


def _required_str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LocationContentError(f"Location missing string field: {field}")
    return value.strip()


def _optional_str(entry: dict[str, Any], field: str) -> str | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LocationContentError(f"Location field must be a string: {field}")
    return value.strip()

_LOCATION_DOCUMENT: list[Any] | None = None


LOCATION_SERVICE = LocationService()


def refresh_location_service(document: list[Any]) -> LocationService:
    global LOCATION_SERVICE
    global _LOCATION_DOCUMENT
    _LOCATION_DOCUMENT = document
    LOCATION_SERVICE = LocationService(document=document)
    return LOCATION_SERVICE
