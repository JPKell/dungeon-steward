"""Add enemy and dungeon asset references.

Revision ID: 20260707_0009
Revises: 20260706_0008
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260707_0009"
down_revision = "20260706_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_dungeon_levels") as batch:
        batch.add_column(sa.Column("thumbnail_asset", sa.String(length=160)))

    with op.batch_alter_table("content_enemies") as batch:
        batch.add_column(sa.Column("thumbnail_asset", sa.String(length=160)))
        batch.add_column(sa.Column("emoji_asset", sa.String(length=160)))
    with op.batch_alter_table("content_equipment_items") as batch:
        batch.add_column(sa.Column("subtype", sa.String(length=160)))

def downgrade() -> None:
    with op.batch_alter_table("content_enemies") as batch:
        batch.drop_column("emoji_asset")
        batch.drop_column("thumbnail_asset")

    with op.batch_alter_table("content_dungeon_levels") as batch:
        batch.drop_column("thumbnail_asset")

    with op.batch_alter_table("content_equipment_items") as batch:
        batch.drop_column("subtype")

