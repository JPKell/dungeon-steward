from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.config import (
    BASE_ATTACK,
    BASE_COMBAT_XP_TO_NEXT_LEVEL,
    BASE_DEFENSE,
    BASE_PLAYER_HP,
    BASE_SPEED,
    MAX_ENERGY,
    PROGRESSION_SCHEMA_VERSION,
)
from bot.database.base import Base, TimestampMixin
from bot.utils.time import utc_now


class Player(TimestampMixin, Base):
    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("discord_user_id", "guild_id", name="uq_player_user_guild"),
        UniqueConstraint("defense_session_id", name="uq_players_defense_session_id"),
        Index("ix_players_guild_xp", "guild_id", "experience"),
        Index("ix_players_active_defense", "is_defending", "defense_started_at"),
    )
              
    id: Mapped[int]                                    = mapped_column(primary_key=True)
    discord_user_id: Mapped[int]                       = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str]                          = mapped_column(String(120), nullable=False)
    guild_id: Mapped[int]                              = mapped_column(BigInteger, nullable=False)
    gold: Mapped[int]                                  = mapped_column(Integer, default=0)
    experience: Mapped[int]                            = mapped_column(Integer, default=0)
    explore_level: Mapped[int]                         = mapped_column(Integer, default=1)
    combat_level: Mapped[int]                          = mapped_column(Integer, default=1)
    combat_xp: Mapped[int]                             = mapped_column(Integer, default=0)
    combat_xp_to_next_level: Mapped[int]               = mapped_column(Integer, default=BASE_COMBAT_XP_TO_NEXT_LEVEL)
    unspent_stat_points: Mapped[int]                   = mapped_column(Integer, default=0)
    current_hp: Mapped[int]                            = mapped_column(Integer, default=BASE_PLAYER_HP)
    max_hp: Mapped[int]                                = mapped_column(Integer, default=BASE_PLAYER_HP)
    attack: Mapped[int]                                = mapped_column(Integer, default=BASE_ATTACK)
    defense: Mapped[int]                               = mapped_column(Integer, default=BASE_DEFENSE)
    speed: Mapped[int]                                 = mapped_column(Integer, default=BASE_SPEED)
    energy: Mapped[int]                                = mapped_column(Integer, default=MAX_ENERGY)
    energy_updated_at: Mapped[datetime]                = mapped_column(DateTime(timezone=True), default=utc_now)
    total_explorations: Mapped[int]                    = mapped_column(Integer, default=0)
    successful_explorations: Mapped[int]               = mapped_column(Integer, default=0)
    failed_explorations: Mapped[int]                   = mapped_column(Integer, default=0)
    hero_influence: Mapped[int]                        = mapped_column(Integer, default=0)
    villain_influence: Mapped[int]                     = mapped_column(Integer, default=0)
    discoveries_found: Mapped[int]                     = mapped_column(Integer, default=0)
    defense_wins: Mapped[int]                          = mapped_column(Integer, default=0)
    highest_unlocked_dungeon_level: Mapped[int]        = mapped_column(Integer, default=1)
    highest_completed_dungeon_level: Mapped[int]       = mapped_column(Integer, default=1)
    progression_schema_version: Mapped[int]            = mapped_column(Integer, default=PROGRESSION_SCHEMA_VERSION)
    last_exploration_at: Mapped[datetime | None]       = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool]                            = mapped_column(Boolean, default=True)
    is_defending: Mapped[bool]                         = mapped_column(Boolean, default=False)
    defense_started_at: Mapped[datetime | None]        = mapped_column(DateTime(timezone=True))
    defense_selected_dungeon_level: Mapped[int | None] = mapped_column(Integer)
    defense_starting_hp: Mapped[int | None]            = mapped_column(Integer)
    defense_session_id: Mapped[str | None]             = mapped_column(String(64))
    defense_channel_id: Mapped[int | None]             = mapped_column(BigInteger)
    defense_guild_id: Mapped[int | None]               = mapped_column(BigInteger)
    defense_message_id: Mapped[int | None]             = mapped_column(BigInteger)
    weapon: Mapped[str | None]                         = mapped_column(String(120))
    shield: Mapped[str | None]                         = mapped_column(String(120))
    helm: Mapped[str | None]                           = mapped_column(String(120))
    armor: Mapped[str | None]                          = mapped_column(String(120))
    gloves: Mapped[str | None]                         = mapped_column(String(120))
    trinket: Mapped[str | None]                        = mapped_column(String(120))
    boots: Mapped[str | None]                          = mapped_column(String(120))

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
    weekly_difficulty_index: Mapped[float] = mapped_column(Float, default=1.0)


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
    dungeon_level: Mapped[int] = mapped_column(Integer, default=1)
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
    dungeon_level: Mapped[int] = mapped_column(Integer, default=1)
    gold_awarded: Mapped[int] = mapped_column(Integer, default=0)
    experience_awarded: Mapped[int] = mapped_column(Integer, default=0)
    discovery_key: Mapped[str | None] = mapped_column(String(120))
    potion_item_key: Mapped[str | None] = mapped_column(String(120))


class PotionInventoryStack(TimestampMixin, Base):
    __tablename__ = "potion_inventory_stacks"
    __table_args__ = (
        UniqueConstraint("player_id", "item_key", name="uq_potion_inventory_player_item"),
        CheckConstraint("quantity >= 0", name="ck_potion_inventory_quantity_nonnegative"),
        Index("ix_potion_inventory_player", "player_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    item_key: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class PotionActivation(TimestampMixin, Base):
    __tablename__ = "potion_activations"
    __table_args__ = (
        UniqueConstraint("player_id", "idempotency_token", name="uq_potion_activation_player_token"),
        Index("ix_potion_activation_player_time", "player_id", "activated_at", "effective_ends_at"),
        Index("ix_potion_activation_player_group", "player_id", "effect_group", "effective_ends_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    item_key: Mapped[str] = mapped_column(String(120), nullable=False)
    effect_group: Mapped[str] = mapped_column(String(40), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_token: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminAuditLog(TimestampMixin, Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_admin_audit_admin_created", "administrator_identity", "created_at"),
        Index("ix_admin_audit_target_user", "target_user_id", "created_at"),
        Index("ix_admin_audit_action", "action_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    administrator_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    administrator_role: Mapped[str] = mapped_column(String(40), nullable=False)
    environment: Mapped[str] = mapped_column(String(40), nullable=False)
    action_name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_domain: Mapped[str] = mapped_column(String(80), nullable=False)
    target_table: Mapped[str | None] = mapped_column(String(120))
    target_user_id: Mapped[int | None] = mapped_column(Integer)
    target_record_id: Mapped[str | None] = mapped_column(String(160))
    previous_values: Mapped[str | None] = mapped_column(Text)
    new_values: Mapped[str | None] = mapped_column(Text)
    quantity_changed: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(40), default="success")
    error_info: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[str] = mapped_column(String(80), nullable=False)


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
    __table_args__ = (
        Index("ix_weekly_guild_active", "guild_id", "resolved_at"),
        Index(
            "uq_weekly_guild_active_unresolved",
            "guild_id",
            unique=True,
            sqlite_where=text("resolved_at IS NULL"),
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

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
    metric: Mapped[str] = mapped_column(String(80), default="explorations")
    mode: Mapped[str] = mapped_column(String(40), default="explore")
    effort_tier: Mapped[int] = mapped_column(Integer, default=1)
    difficulty_index: Mapped[float] = mapped_column(Float, default=1.0)
    previous_participant_count: Mapped[int] = mapped_column(Integer, default=1)
    participant_factor: Mapped[float] = mapped_column(Float, default=1.0)
    raw_target_value: Mapped[float] = mapped_column(Float, default=1.0)
    rounded_target_value: Mapped[int] = mapped_column(Integer, default=1)
    succeeded: Mapped[bool | None] = mapped_column(Boolean)
    schema_version: Mapped[int] = mapped_column(Integer, default=2)
    reward_policy_version: Mapped[int] = mapped_column(Integer, default=1)
    participant_count: Mapped[int] = mapped_column(Integer, default=0)


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


class WeeklyObjectiveEvent(TimestampMixin, Base):
    __tablename__ = "weekly_objective_events"
    __table_args__ = (
        UniqueConstraint("weekly_objective_id", "event_id", name="uq_weekly_objective_event"),
        Index("ix_weekly_objective_events_metric", "weekly_objective_id", "metric"),
        Index("ix_weekly_objective_events_unique", "weekly_objective_id", "metric", "unique_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    weekly_objective_id: Mapped[int] = mapped_column(ForeignKey("weekly_objectives.id"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    unique_key: Mapped[str | None] = mapped_column(String(160))
    metadata_json: Mapped[str | None] = mapped_column(Text)


class WeeklyObjectiveReward(TimestampMixin, Base):
    __tablename__ = "weekly_objective_rewards"
    __table_args__ = (
        UniqueConstraint("objective_id", "user_id", name="uq_weekly_objective_reward_user"),
        Index("ix_weekly_objective_rewards_objective", "objective_id", "awarded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("weekly_objectives.id"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    explore_level_used: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_equipment_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    effort_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    contribution: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_required_contribution: Mapped[int] = mapped_column(Integer, nullable=False)
    gold_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
