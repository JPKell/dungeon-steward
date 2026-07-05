from __future__ import annotations

import argparse
import json
from pathlib import Path

from bot.config import load_settings
from bot.database.session import make_engine, make_session_factory, session_scope
from bot.services.content_database import CONTENT_DIR, dump_content_to_files, load_content_from_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Load or dump Dungeon Steward content JSON through the database.")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to DATABASE_URL from the environment.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    load_parser = subparsers.add_parser("load", help="Load JSON files into content tables.")
    load_parser.add_argument("--content-dir", type=Path, default=CONTENT_DIR)
    load_parser.add_argument(
        "--skip-runtime-discovery-sync",
        action="store_true",
        help="Do not also update the existing discoveries runtime table.",
    )

    dump_parser = subparsers.add_parser("dump", help="Dump content tables back to JSON files.")
    dump_parser.add_argument("--content-dir", type=Path, default=CONTENT_DIR)
    dump_parser.add_argument("--indent", type=int, default=2)

    args = parser.parse_args()
    database_url = args.database_url or load_settings(require_token=False).database_url
    engine = make_engine(database_url)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        if args.command == "load":
            result = load_content_from_files(
                session,
                content_dir=args.content_dir,
                sync_runtime_discoveries=not args.skip_runtime_discovery_sync,
            )
        else:
            result = dump_content_to_files(session, content_dir=args.content_dir, indent=args.indent)

    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
