from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import Discovery, Player, PlayerDiscovery
from bot.utils.time import utc_now


class DiscoveryService:
    def __init__(
        self,
        content_path: Path | None = None,
        *,
        document: list[Any] | None = None,
    ) -> None:
        self.content_path = content_path or Path(__file__).parents[1] / "content" / "discoveries.json"
        self._document = document

    def load_content(self) -> list[dict[str, Any]]:
        content = self._document
        if content is None:
            content = _DISCOVERY_DOCUMENT
        if content is None:
            content = json.loads(self.content_path.read_text(encoding="utf-8"))
        if len(content) < 15:
            raise ValueError("At least 15 discoveries are required")
        keys: set[str] = set()
        for item in content:
            key = item["key"]
            if key in keys:
                raise ValueError(f"Duplicate discovery key: {key}")
            keys.add(key)
        return content

    def sync_content(self, session: Session) -> None:
        for item in self.load_content():
            discovery = session.scalar(select(Discovery).where(Discovery.key == item["key"]))
            if discovery is None:
                discovery = Discovery(key=item["key"])
                session.add(discovery)
            discovery.name = item["name"]
            discovery.description = item["description"]
            discovery.category = item["category"]
            discovery.rarity = item.get("rarity", "common")
            discovery.image_url = item.get("image_url")
            discovery.enabled = bool(item.get("enabled", True))

    def award(self, session: Session, player: Player, discovery_key: str | None) -> tuple[Discovery | None, bool]:
        if not discovery_key:
            return None, False
        discovery = session.scalar(
            select(Discovery).where(Discovery.key == discovery_key, Discovery.enabled.is_(True))
        )
        if discovery is None:
            return None, False
        existing = session.scalar(
            select(PlayerDiscovery).where(
                PlayerDiscovery.player_id == player.id,
                PlayerDiscovery.discovery_id == discovery.id,
            )
        )
        if existing:
            existing.times_found += 1
            existing.last_found_at = utc_now()
            player.gold += 2
            return discovery, False
        session.add(PlayerDiscovery(player_id=player.id, discovery_id=discovery.id))
        player.discoveries_found += 1
        return discovery, True


_DISCOVERY_DOCUMENT: list[Any] | None = None


def refresh_discovery_content(document: list[Any]) -> None:
    global _DISCOVERY_DOCUMENT
    _DISCOVERY_DOCUMENT = document
