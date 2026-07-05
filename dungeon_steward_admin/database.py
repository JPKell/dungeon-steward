from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bot.database.session import make_engine, make_session_factory
from dungeon_steward_admin.config import AdminRuntimeConfig


def build_engine(config: AdminRuntimeConfig) -> Engine:
    engine = make_engine(config.database_url)
    if config.statement_timeout_ms and not config.database_url.startswith("sqlite"):
        with engine.begin() as connection:
            connection.execute(text("SET statement_timeout = :timeout"), {"timeout": config.statement_timeout_ms})
    return engine


def build_session_factory(config: AdminRuntimeConfig) -> sessionmaker[Session]:
    return make_session_factory(build_engine(config))
