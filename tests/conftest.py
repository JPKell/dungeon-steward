from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bot.database.base import Base
from bot.services.discovery_service import DiscoveryService


@pytest.fixture()
def now() -> datetime:
    return datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        DiscoveryService().sync_content(db)
        db.commit()
    yield factory


@pytest.fixture()
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
        session.rollback()


def make_player(db: Session, *, now: datetime, user_id: int = 1, guild_id: int = 10):
    from bot.models import Player

    player = Player(
        discord_user_id=user_id,
        guild_id=guild_id,
        display_name=f"User {user_id}",
        energy_updated_at=now,
    )
    db.add(player)
    db.flush()
    return player
