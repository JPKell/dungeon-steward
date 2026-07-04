from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.config import MAX_ENERGY
from bot.database.base import Base, TimestampMixin
from bot.utils.time import utc_now


class Player(TimestampMixin, Base):
    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("discord_user_id", "guild_id", name="uq_player_user_guild"),
        Index("ix_players_guild_xp", "guild_id", "experience"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gold: Mapped[int] = mapped_column(Integer, default=0)
    experience: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    energy: Mapped[int] = mapped_column(Integer, default=MAX_ENERGY)
    energy_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    total_explorations: Mapped[int] = mapped_column(Integer, default=0)
    successful_explorations: Mapped[int] = mapped_column(Integer, default=0)
    failed_explorations: Mapped[int] = mapped_column(Integer, default=0)
    hero_influence: Mapped[int] = mapped_column(Integer, default=0)
    villain_influence: Mapped[int] = mapped_column(Integer, default=0)
    discoveries_found: Mapped[int] = mapped_column(Integer, default=0)
    last_exploration_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    discoveries: Mapped[list[PlayerDiscovery]] = relationship(back_populates="player")


class GuildDungeon(TimestampMixin, Base):
    __tablename__ = "guild_dungeons"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Kellrond Community Dungeon")
    level: Mapped[int] = mapped_column(Integer, default=1)
    gold: Mapped[int] = mapped_column(Integer, default=0)
    hero_influence: Mapped[int] = mapped_column(Integer, default=0)
    villain_influence: Mapped[int] = mapped_column(Integer, default=0)
    stability: Mapped[int] = mapped_column(Integer, default=50)
    total_explorations: Mapped[int] = mapped_column(Integer, default=0)
    heroes_defeated: Mapped[int] = mapped_column(Integer, default=0)
    rooms_discovered: Mapped[int] = mapped_column(Integer, default=0)
    current_week_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExplorationSession(TimestampMixin, Base):
    __tablename__ = "exploration_sessions"
    __table_args__ = (
        Index("ix_exploration_active_player", "player_id", "resolved_at", "expires_at"),
        UniqueConstraint("resolution_key", name="uq_exploration_resolution_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resolution_key: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    encounter_key: Mapped[str] = mapped_column(String(120), nullable=False)
    selected_choice_key: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EncounterHistory(TimestampMixin, Base):
    __tablename__ = "encounter_history"
    __table_args__ = (UniqueConstraint("exploration_session_id", name="uq_history_session"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exploration_session_id: Mapped[int] = mapped_column(
        ForeignKey("exploration_sessions.id"), nullable=False
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    encounter_key: Mapped[str] = mapped_column(String(120), nullable=False)
    choice_key: Mapped[str] = mapped_column(String(120), nullable=False)
    gold_awarded: Mapped[int] = mapped_column(Integer, default=0)
    experience_awarded: Mapped[int] = mapped_column(Integer, default=0)
    discovery_key: Mapped[str | None] = mapped_column(String(120))


class Discovery(TimestampMixin, Base):
    __tablename__ = "discoveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    rarity: Mapped[str] = mapped_column(String(40), default="common")
    image_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    players: Mapped[list[PlayerDiscovery]] = relationship(back_populates="discovery")


class PlayerDiscovery(TimestampMixin, Base):
    __tablename__ = "player_discoveries"
    __table_args__ = (UniqueConstraint("player_id", "discovery_id", name="uq_player_discovery"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    discovery_id: Mapped[int] = mapped_column(ForeignKey("discoveries.id"), nullable=False)
    times_found: Mapped[int] = mapped_column(Integer, default=1)
    first_found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    player: Mapped[Player] = relationship(back_populates="discoveries")
    discovery: Mapped[Discovery] = relationship(back_populates="players")


class WeeklyObjective(TimestampMixin, Base):
    __tablename__ = "weekly_objectives"
    __table_args__ = (Index("ix_weekly_guild_active", "guild_id", "resolved_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    objective_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_value: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_value: Mapped[int] = mapped_column(Integer, default=0)
    reward_gold: Mapped[int] = mapped_column(Integer, default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rewards_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeeklyPlayerContribution(TimestampMixin, Base):
    __tablename__ = "weekly_player_contributions"
    __table_args__ = (
        UniqueConstraint("weekly_objective_id", "player_id", name="uq_weekly_player"),
        Index("ix_weekly_contribution_value", "weekly_objective_id", "contribution_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    weekly_objective_id: Mapped[int] = mapped_column(ForeignKey("weekly_objectives.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    contribution_value: Mapped[int] = mapped_column(Integer, default=0)
