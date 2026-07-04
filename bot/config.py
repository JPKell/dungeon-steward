from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from bot.services.progression_content import PROGRESSION_CONTENT

BASE_EXPLORE_COOLDOWN_MINUTES = PROGRESSION_CONTENT.exploration.base_cooldown_minutes
MIN_EXPLORE_COOLDOWN_MINUTES = PROGRESSION_CONTENT.exploration.min_cooldown_minutes
ENERGY_REGEN_SECONDS = BASE_EXPLORE_COOLDOWN_MINUTES * 60
MAX_ENERGY = 12
EXPLORATION_ENERGY_COST = 1
EXPLORATION_TIMEOUT_SECONDS = 5 * 60
GAME_VERSION = "0.1.0"
PROGRESSION_SCHEMA_VERSION = PROGRESSION_CONTENT.schema_version

BASE_PLAYER_HP = PROGRESSION_CONTENT.new_player.base_hp
BASE_COMBAT_XP_TO_NEXT_LEVEL = int(PROGRESSION_CONTENT.combat_leveling.xp_to_next_level.base)
HP_PER_COMBAT_LEVEL = int(PROGRESSION_CONTENT.combat_leveling.hp_per_level.base)
COMBAT_STAT_POINTS_PER_LEVEL = int(PROGRESSION_CONTENT.combat_leveling.stat_points_per_level.base)
BASE_ATTACK = PROGRESSION_CONTENT.new_player.attack
BASE_DEFENSE = PROGRESSION_CONTENT.new_player.defense
BASE_SPEED = PROGRESSION_CONTENT.new_player.speed
POST_DEFEAT_HP_PERCENT = PROGRESSION_CONTENT.defense.post_defeat_hp_percent
MINIMUM_DAMAGE = PROGRESSION_CONTENT.defense.minimum_damage
MAX_BATTLE_ROUNDS = PROGRESSION_CONTENT.defense.max_battle_rounds

BASE_PLAYER_HP = PROGRESSION_CONTENT.new_player.base_hp
HP_PER_COMBAT_LEVEL = int(PROGRESSION_CONTENT.combat_leveling.hp_per_level.base)
COMBAT_STAT_POINTS_PER_LEVEL = int(PROGRESSION_CONTENT.combat_leveling.stat_points_per_level.base)
BASE_ATTACK = PROGRESSION_CONTENT.new_player.attack
BASE_DEFENSE = PROGRESSION_CONTENT.new_player.defense
BASE_SPEED = PROGRESSION_CONTENT.new_player.speed
POST_DEFEAT_HP_PERCENT = PROGRESSION_CONTENT.defense.post_defeat_hp_percent
MINIMUM_DAMAGE = PROGRESSION_CONTENT.defense.minimum_damage
MAX_BATTLE_ROUNDS = PROGRESSION_CONTENT.defense.max_battle_rounds


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
