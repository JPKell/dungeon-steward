# Dungeon Steward

Dungeon Steward is a Discord slash-command bot for the Kellrond Games community. It runs a lightweight dungeon exploration and defense game with regenerating energy, encounter choices, discoveries, combat progression, player profiles, shared server dungeon progress, weekly objectives, and staff controls.

## Features

- `/dungeon` slash commands only; no prefix commands and no Message Content intent.
- Explore Level is separate from Combat Level. Explore Level comes from exploration XP and shortens energy recovery down to a 30-minute floor.
- Combat Level, Combat XP, HP, attack, defense, speed, and unspent stat points are persisted per player.
- Defending sessions survive bot restarts and resolve lazily from timestamps: one battle per completed minute, capped by Combat Level.
- Dungeon defense levels 1-20 use content-driven enemy definitions and scaling.
- Equipment definitions live in `bot/content/equipment.json`, and the shop refreshes 10 Combat Level-appropriate items each hour.
- Equipment slots are persisted for weapon, shield, helm, armor, gloves, trinket, and boots.
- Reusable Discord embed images are catalogued locally and synchronized once to a private asset channel.
- Energy regenerates lazily, capped at 12.
- Replayable content-driven encounters in `bot/content/encounters.json`.
- Discoveries and collectibles in `bot/content/discoveries.json`.
- SQLAlchemy models with Alembic migrations.
- PostgreSQL for production, SQLite for local development.
- Discord embeds, buttons, private error responses, and staff-only admin commands.
- Tests for energy, exploration idempotency, combat progression, defense resolution, content validation, weekly objectives, leaderboards, and permissions.

## Technology

- Python 3.12+
- `discord.py`
- SQLAlchemy
- Alembic
- PostgreSQL or SQLite
- `python-dotenv`
- Pillow for offline image preparation
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
DISCORD_ASSET_CHANNEL_ID=
```

Run migrations:

```bash
alembic upgrade head
python -m scripts.content_db load
```

Or build a fresh local SQLite development database in one step:

```bash
python -m scripts.build_dev_db --reset
```

Validate content and run tests:

```bash
python -m scripts.validate_content
python -m scripts.prepare_discord_assets --validate
ruff check .
pytest
```

Prepare and synchronize Discord embed images:

```bash
python -m scripts.prepare_discord_assets --prepare
python -m scripts.sync_discord_assets --dry-run
python -m scripts.sync_discord_assets
```

See [docs/DISCORD_IMAGES.md](docs/DISCORD_IMAGES.md) for image dimensions, naming conventions, asset-channel permissions, replacement flow, and local fallback behavior.

Run the bot:

```bash
python -m bot.main
```

With `DISCORD_TEST_GUILD_ID` set, commands sync to one test server for fast development. For production, unset it and set `ENVIRONMENT=production` to sync global commands.

Run the terminal admin console:

```bash
python -m dungeon_steward_admin --environment development --admin local-admin
```

Configure `DUNGEON_ADMIN_IDENTITIES` before launching. See [docs/admin_console.md](docs/admin_console.md) for production read-only mode, write confirmation, audit logging, table CRUD, and custom actions.

## Commands

Player commands:

- `/dungeon explore`
- `/dungeon defend dungeon_level:1-20`
- `/dungeon stop-defending`
- `/dungeon shop`
- `/dungeon buy item_number:1-10`
- `/dungeon stats [stat] [amount]`
- `/dungeon hall`
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

New players start with 12 energy. Exploration costs 1 energy. Energy regenerates lazily from `energy_updated_at`, so offline time counts and restarts do not reset progress. Explore Level 1 uses the base 120-minute recovery; each Explore Level gained reduces that by 1 minute, with a 30-minute minimum. When a player is full, the timestamp is refreshed so stored time cannot exceed the 24-hour cap.

## Progression And Defense

Exploration XP now advances `explore_level`. Existing player `level` values are migrated into `explore_level` by Alembic revision `20260703_0002`.

Combat progression is independent. Players have `combat_level`, `combat_xp`, `combat_xp_to_next_level`, `current_hp`, `max_hp`, `attack`, `defense`, `speed`, and `unspent_stat_points`. Each Combat Level grants 2 stat points and increases maximum HP.

`/dungeon defend` starts a persistent defense session for a selected dungeon level from 1 through 20. A session resolves when the player stops defending, explores, or reaches their Combat Level duration cap. Resolution simulates one enemy battle per completed minute, carries player HP between battles, awards Combat XP and gold for victories, and sends a separate defense report before any exploration result.

`/dungeon stats` shows combat stats. Passing a stat and amount spends unspent points on attack, defense, or speed.

Equipment slots are present in the player record for weapon, shield, helm, armor, gloves, boots, and trinket. The shop offers 10 items at a time from database-backed equipment content; stock is generated from the current UTC hour rounded down and the player's Combat Level, so players at the same Combat Level see the same stock during the same hour. Shop item costs and stat bonuses can scale by Combat Level through database-backed progression content. Buying an item spends gold and equips it immediately in the matching slot.

SQLite is useful for local development, but production concurrency should use PostgreSQL. The schema uses uniqueness constraints for exploration resolution and player records; PostgreSQL is the recommended database when many interactions can arrive at once.

## Content Format

Runtime content lives in dedicated database tables. The JSON files in `bot/content` are import/export artifacts for editing, review, and version control.

Encounters have a unique `key`, title, description, category, weight, enabled flag, rarity, and two to four choices. Choices define result text, reward ranges, influence effects, stability changes, optional discovery keys, and success state.

Discoveries have a unique key, name, description, category, rarity, optional image URL, and enabled flag.

Equipment items have a unique key, name, slot, rarity, level range, gold cost, and HP/attack/defense/speed bonuses. Shop stock is deterministic per UTC hour and Combat Level, with optional curve scaling for displayed cost and stats.

Enemies have a dungeon level range, base stat ranges, stage modifiers, reward ranges, weight, and enabled flag.

Dungeon defense scaling defines the possible enemy level range plus stat and reward modifiers for each level.

Progression and combat tuning includes exploration cooldowns, Explore Level XP curves, exploration gold/XP reward multipliers, new-player combat defaults, Combat Level XP requirements, scalable HP gained per Combat Level, scalable stat points per Combat Level, defense duration growth, defense recovery, combat round limits, enemy generation scaling, and shop rarity, cost, and stat scaling. Explore Level and the reusable scale blocks support `linear`, `quadratic`, and `exponential` curves while preserving the current balance by default.

After editing content:

```bash
python -m scripts.validate_content
```

Load the JSON files into the database after migrations, and dump database content back to JSON when you want to review or commit it:

```bash
python -m scripts.content_db load
python -m scripts.content_db dump --content-dir bot/content
```

The bot hydrates runtime content from the database at startup. `/dungeon-admin reload-content` refreshes the running bot from the database without reading JSON files.

## PostgreSQL Production Setup

Example database setup:

```bash
sudo -u postgres createuser --pwprompt kellrond_bot
sudo -u postgres createdb --owner=kellrond_bot kellrond_discord_bot
```

Set:

```dotenv
DATABASE_URL=postgresql+psycopg://kellrond_bot:password@localhost:5432/kellrond_discord_bot
DISCORD_ASSET_CHANNEL_ID=
```

Run:

```bash
alembic upgrade head
python -m scripts.content_db load
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
sudo -u kellrond-bot .venv/bin/python -m scripts.content_db load
sudo -u kellrond-bot .venv/bin/python -m scripts.prepare_discord_assets --validate
sudo -u kellrond-bot .venv/bin/python -m scripts.sync_discord_assets --dry-run
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
