from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from bot.config import load_settings
from bot.database.session import make_engine, make_session_factory, session_scope
from bot.services.content_database import CONTENT_DIR, load_content_from_files

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local development database from scratch, then load content JSON."
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy SQLite database URL. Defaults to DATABASE_URL from the environment.",
    )
    parser.add_argument("--content-dir", type=Path, default=CONTENT_DIR)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing SQLite database file before running migrations.",
    )
    parser.add_argument(
        "--skip-runtime-discovery-sync",
        action="store_true",
        help="Do not also update the runtime discoveries table while loading content.",
    )
    args = parser.parse_args()

    database_url = args.database_url or load_settings(require_token=False).database_url
    database_path = _sqlite_database_path(database_url)
    if database_path is None:
        raise SystemExit("This development builder only supports file-backed SQLite database URLs.")

    if database_path.exists():
        if not args.reset:
            raise SystemExit(
                f"{database_path} already exists. Re-run with --reset to rebuild it from scratch."
            )
        database_path.unlink()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ["DATABASE_URL"] = database_url
    alembic_config = Config(str(DEFAULT_ALEMBIC_CONFIG))
    command.upgrade(alembic_config, "head")

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        load_result = load_content_from_files(
            session,
            content_dir=args.content_dir,
            sync_runtime_discoveries=not args.skip_runtime_discovery_sync,
        )

    print(
        json.dumps(
            {
                "database_url": database_url,
                "database_path": str(database_path),
                "reset": args.reset,
                "alembic_revision": "head",
                "content": load_result.as_dict(),
            },
            indent=2,
        )
    )


def _sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


if __name__ == "__main__":
    main()
