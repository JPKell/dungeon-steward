"""Add explore/combat progression and defending state.

Revision ID: 20260703_0002
Revises: 20260703_0001
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260703_0002"
down_revision = "20260703_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("players") as batch_op:
        batch_op.alter_column(
            "level",
            new_column_name="explore_level",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("combat_level", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("combat_xp", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("combat_xp_to_next_level", sa.Integer(), nullable=False, server_default="100")
        )
        batch_op.add_column(
            sa.Column("unspent_stat_points", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("current_hp", sa.Integer(), nullable=False, server_default="50"))
        batch_op.add_column(sa.Column("max_hp", sa.Integer(), nullable=False, server_default="50"))
        batch_op.add_column(sa.Column("attack", sa.Integer(), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column("defense", sa.Integer(), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column("speed", sa.Integer(), nullable=False, server_default="5"))
        batch_op.add_column(
            sa.Column("is_defending", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("defense_started_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("defense_selected_dungeon_level", sa.Integer()))
        batch_op.add_column(sa.Column("defense_starting_hp", sa.Integer()))
        batch_op.add_column(sa.Column("defense_session_id", sa.String(length=64)))
        batch_op.add_column(sa.Column("defense_channel_id", sa.BigInteger()))
        batch_op.add_column(sa.Column("defense_guild_id", sa.BigInteger()))
        batch_op.add_column(sa.Column("defense_message_id", sa.BigInteger()))
        batch_op.add_column(sa.Column("weapon", sa.String(length=120)))
        batch_op.add_column(sa.Column("shield", sa.String(length=120)))
        batch_op.add_column(sa.Column("helm", sa.String(length=120)))
        batch_op.add_column(sa.Column("armor", sa.String(length=120)))
        batch_op.add_column(sa.Column("gloves", sa.String(length=120)))
        batch_op.add_column(sa.Column("trinket", sa.String(length=120)))
        batch_op.add_column(sa.Column("boots", sa.String(length=120)))
        batch_op.create_unique_constraint("uq_players_defense_session_id", ["defense_session_id"])
    op.create_index("ix_players_active_defense", "players", ["is_defending", "defense_started_at"])


def downgrade() -> None:
    op.drop_index("ix_players_active_defense", table_name="players")
    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_constraint("uq_players_defense_session_id", type_="unique")
        batch_op.drop_column("boots")
        batch_op.drop_column("trinket")
        batch_op.drop_column("gloves")
        batch_op.drop_column("armor")
        batch_op.drop_column("helm")
        batch_op.drop_column("shield")
        batch_op.drop_column("weapon")
        batch_op.drop_column("defense_message_id")
        batch_op.drop_column("defense_guild_id")
        batch_op.drop_column("defense_channel_id")
        batch_op.drop_column("defense_session_id")
        batch_op.drop_column("defense_starting_hp")
        batch_op.drop_column("defense_selected_dungeon_level")
        batch_op.drop_column("defense_started_at")
        batch_op.drop_column("is_defending")
        batch_op.drop_column("speed")
        batch_op.drop_column("defense")
        batch_op.drop_column("attack")
        batch_op.drop_column("max_hp")
        batch_op.drop_column("current_hp")
        batch_op.drop_column("unspent_stat_points")
        batch_op.drop_column("combat_xp_to_next_level")
        batch_op.drop_column("combat_xp")
        batch_op.drop_column("combat_level")
        batch_op.alter_column(
            "explore_level",
            new_column_name="level",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
