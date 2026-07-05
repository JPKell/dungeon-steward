from __future__ import annotations

import argparse
import getpass
import sys

from bot.config import load_settings
from bot.logging_config import configure_logging
from dungeon_steward_admin.app import AdminConsoleApp
from dungeon_steward_admin.config import ProductionConfirmationError, load_runtime_config
from dungeon_steward_admin.database import build_session_factory
from dungeon_steward_admin.permissions import AdminConfigurationError, PermissionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dungeon Steward terminal administration console")
    parser.add_argument("--environment", choices=("development", "staging", "production"))
    parser.add_argument("--read-only", action="store_true", help="Disable all writes")
    parser.add_argument("--user", help="Open with a user search or direct ID lookup")
    parser.add_argument("--admin", help="Administrator identity from DUNGEON_ADMIN_IDENTITIES")
    parser.add_argument("--debug", action="store_true", help="Show full exceptions in development")
    args = parser.parse_args(argv)

    settings = load_settings(require_token=False)
    configure_logging(settings.log_level)
    environment = (args.environment or settings.environment or "development").lower()
    production_confirmed = False
    if environment == "production" and not args.read_only:
        print("PRODUCTION environment selected with writes enabled.")
        print("Database credentials are not displayed. Writes will be audited.")
        phrase = getpass.getpass("Type PRODUCTION to continue: ")
        production_confirmed = phrase == "PRODUCTION"

    try:
        config = load_runtime_config(
            environment=environment,
            read_only=args.read_only,
            admin_identity=args.admin,
            production_confirmed=production_confirmed,
            settings=settings,
        )
    except (AdminConfigurationError, PermissionError, ProductionConfirmationError) as error:
        print(f"Admin console refused to start: {error}", file=sys.stderr)
        return 2

    session_factory = build_session_factory(config)
    try:
        AdminConsoleApp(config=config, session_factory=session_factory, initial_user=args.user).run()
    except KeyboardInterrupt:
        print("\nAdmin console interrupted. Terminal state restored.")
        return 130
    except Exception as error:
        if args.debug or environment != "production":
            raise
        print(f"Admin console failed: {error.__class__.__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
