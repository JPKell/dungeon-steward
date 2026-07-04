# Dungeon Steward

Dungeon Steward is a Discord slash-command bot for the Kellrond Games community. It runs a lightweight dungeon exploration game with regenerating energy, encounter choices, discoveries, player profiles, shared server dungeon progress, weekly objectives, and staff controls.

## Features

- `/dungeon` slash commands only; no prefix commands and no Message Content intent.
- Energy regenerates lazily: 1 energy every 2 hours, capped at 12.
- Replayable content-driven encounters in `bot/content/encounters.json`.
- Discoveries and collectibles in `bot/content/discoveries.json`.
- SQLAlchemy models with Alembic migrations.
- PostgreSQL for production, SQLite for local development.
- Discord embeds, buttons, private error responses, and staff-only admin commands.
- Tests for energy, exploration idempotency, content validation, weekly objectives, leaderboards, and permissions.

## Technology

- Python 3.12+
- `discord.py`
- SQLAlchemy
- Alembic
- PostgreSQL or SQLite
- `python-dotenv`
- `pytest`, `pytest-asyncio`, `ruff`

## Discord Setup

Create an application in the Discord Developer Portal, add a bot, and copy the bot token into your server environment. Enable only the default bot intents. Do not enable Message Content Intent.

Use an OAuth2 install URL with:

- Scopes: `bot`, `applications.commands`
- Bot permissions: `Send Messages`, `Embed Links`, `Use External Emojis` if desired, `Read Message History`

Do not grant Discord Administrator permission.

## Local Setup

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set values in `.env`:

```dotenv
DISCORD_BOT_TOKEN=
DISCORD_APPLICATION_ID=
DISCORD_TEST_GUILD_ID=
DISCORD_STAFF_ROLE_ID=
DATABASE_URL=sqlite:///./dungeon_steward.sqlite3
LOG_LEVEL=INFO
ENVIRONMENT=development
```

Run migrations:

```bash
alembic upgrade head
```

Validate content and run tests:

```bash
python -m scripts.validate_content
ruff check .
pytest
```

Run the bot:

```bash
python -m bot.main
```

With `DISCORD_TEST_GUILD_ID` set, commands sync to one test server for fast development. For production, unset it and set `ENVIRONMENT=production` to sync global commands.

## Commands

Player commands:

- `/dungeon explore`
- `/dungeon profile [member]`
- `/dungeon energy`
- `/dungeon status`
- `/dungeon leaderboard [category]`
- `/dungeon help`

Staff commands:

- `/dungeon-admin announce`
- `/dungeon-admin grant-energy`
- `/dungeon-admin set-energy`
- `/dungeon-admin reset-player`
- `/dungeon-admin event-status`
- `/dungeon-admin reload-content`

Staff commands require either `Manage Server` permission or the configured `DISCORD_STAFF_ROLE_ID`.

## Energy System

New players start with 12 energy. Exploration costs 1 energy. Energy regenerates lazily from `energy_updated_at`, so offline time counts and restarts do not reset progress. When a player is full, the timestamp is refreshed so stored time cannot exceed the 24-hour cap.

SQLite is useful for local development, but production concurrency should use PostgreSQL. The schema uses uniqueness constraints for exploration resolution and player records; PostgreSQL is the recommended database when many interactions can arrive at once.

## Content Format

Encounters live in `bot/content/encounters.json`. Each encounter has a unique `key`, title, description, category, weight, enabled flag, rarity, and two to four choices. Choices define result text, reward ranges, influence effects, stability changes, optional discovery keys, and success state.

Discoveries live in `bot/content/discoveries.json`. Each discovery has a unique key, name, description, category, rarity, optional image URL, and enabled flag.

After editing content:

```bash
python -m scripts.validate_content
```

Then use `/dungeon-admin reload-content` to sync discoveries into the database.

## PostgreSQL Production Setup

Example database setup:

```bash
sudo -u postgres createuser --pwprompt kellrond_bot
sudo -u postgres createdb --owner=kellrond_bot kellrond_discord_bot
```

Set:

```dotenv
DATABASE_URL=postgresql+psycopg://kellrond_bot:password@localhost:5432/kellrond_discord_bot
```

Run:

```bash
alembic upgrade head
```

## Ubuntu Deployment

Assumed path:

```text
/var/www/kellrond-discord-bot
```

Create a dedicated user:

```bash
sudo useradd --system --home /var/www/kellrond-discord-bot --shell /usr/sbin/nologin kellrond-bot
```

Install the app:

```bash
sudo mkdir -p /var/www/kellrond-discord-bot
sudo chown -R kellrond-bot:kellrond-bot /var/www/kellrond-discord-bot
sudo -u kellrond-bot python3.12 -m venv /var/www/kellrond-discord-bot/.venv
sudo -u kellrond-bot /var/www/kellrond-discord-bot/.venv/bin/pip install -r requirements.txt
```

Create `/etc/kellrond-discord-bot.env` with production values, owned by root and readable by the service:

```bash
sudo chmod 640 /etc/kellrond-discord-bot.env
```

Install and run the service:

```bash
sudo cp deploy/kellrond-discord-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kellrond-discord-bot
sudo systemctl status kellrond-discord-bot
sudo journalctl -u kellrond-discord-bot -f
sudo systemctl restart kellrond-discord-bot
```

## Updates

```bash
cd /var/www/kellrond-discord-bot
sudo -u kellrond-bot git pull
sudo -u kellrond-bot .venv/bin/pip install -r requirements.txt
sudo -u kellrond-bot .venv/bin/alembic upgrade head
sudo systemctl restart kellrond-discord-bot
```

## Token Rotation

Regenerate the token in the Discord Developer Portal, update `/etc/kellrond-discord-bot.env`, and restart:

```bash
sudo systemctl restart kellrond-discord-bot
```

Never commit `.env` or real tokens.

## Backups

For PostgreSQL:

```bash
pg_dump kellrond_discord_bot > kellrond_discord_bot.sql
```

Store backups outside the application server and test restore procedures periodically.

## Troubleshooting

- Commands do not appear: set `DISCORD_TEST_GUILD_ID` for development sync, restart the bot, and check journal logs.
- Bot cannot start: verify `DISCORD_BOT_TOKEN` and `DATABASE_URL`.
- Migrations fail: confirm PostgreSQL credentials and run `alembic current`.
- Content reload fails: run `python -m scripts.validate_content`.
- Interactions time out: check database connectivity and bot logs.

