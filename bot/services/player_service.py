from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.config import MAX_ENERGY, PROGRESSION_SCHEMA_VERSION
from bot.models import GuildDungeon, Player
from bot.services.progression_service import migrate_explore_progression
from bot.utils.time import utc_now


class PlayerService:
    def get_or_create(
        self, session: Session, *, guild_id: int, user_id: int, display_name: str
    ) -> Player:
        player = session.scalar(
            select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id)
        )
        if player is None:
            player = Player(
                guild_id=guild_id,
                discord_user_id=user_id,
                display_name=display_name[:120],
                energy=MAX_ENERGY,
                energy_updated_at=utc_now(),
            )
            session.add(player)
            session.flush()
        else:
            player.display_name = display_name[:120]
        migrate_explore_progression(player)
        player.highest_unlocked_dungeon_level = max(1, int(player.highest_unlocked_dungeon_level or 1))
        player.highest_completed_dungeon_level = max(1, int(player.highest_completed_dungeon_level or 1))
        player.defense_wins = max(0, int(player.defense_wins or 0))
        player.progression_schema_version = max(
            int(player.progression_schema_version or 0),
            PROGRESSION_SCHEMA_VERSION,
        )
        return player

    def get_or_create_guild(self, session: Session, *, guild_id: int) -> GuildDungeon:
        dungeon = session.scalar(select(GuildDungeon).where(GuildDungeon.discord_guild_id == guild_id))
        if dungeon is None:
            dungeon = GuildDungeon(discord_guild_id=guild_id)
            session.add(dungeon)
            session.flush()
        return dungeon


def title_for_player(player: Player) -> str:
    if player.explore_level >= 10 or player.total_explorations >= 100:
        return "Apprentice Dungeon Master"
    if player.discoveries_found >= 20:
        return "Dungeon Steward"
    if player.gold >= 500:
        return "Keeper of Keys"
    if player.total_explorations >= 25:
        return "Goblin Supervisor"
    if player.total_explorations >= 5:
        return "Corridor Scout"
    return "Dungeon Visitor"
