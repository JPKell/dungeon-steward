from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

ENERGY_REGEN_SECONDS = 2 * 60 * 60
MAX_ENERGY = 12
EXPLORATION_ENERGY_COST = 1
EXPLORATION_TIMEOUT_SECONDS = 5 * 60
GAME_VERSION = "0.1.0"


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    discord_application_id: int | None
    discord_test_guild_id: int | None
    discord_staff_role_id: int | None
    database_url: str
    log_level: str
    environment: str

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def load_settings(*, require_token: bool = True) -> Settings:
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./dungeon_steward.sqlite3")
    if require_token and not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return Settings(
        discord_bot_token=token,
        discord_application_id=_optional_int(os.getenv("DISCORD_APPLICATION_ID")),
        discord_test_guild_id=_optional_int(os.getenv("DISCORD_TEST_GUILD_ID")),
        discord_staff_role_id=_optional_int(os.getenv("DISCORD_STAFF_ROLE_ID")),
        database_url=database_url,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        environment=os.getenv("ENVIRONMENT", "development"),
    )

