# Production Launch Guide

This guide deploys Dungeon Steward on an Ubuntu web server with PostgreSQL, systemd, Discord-hosted visual assets, and optional Nginx/DNS/TLS setup.

Dungeon Steward is a Discord Gateway bot, not an HTTP webhook app. It does not currently expose application endpoints for Nginx to reverse proxy. Nginx is still useful on the same server for TLS, a landing page, a static health URL, or future web tools, but Discord slash commands are delivered over the bot connection to Discord.

## 1. Prepare Discord

1. Create or open the application in the Discord Developer Portal.
2. Add a bot and copy the bot token. Treat it like a password.
3. Enable only the default bot intents. Do not enable Message Content Intent.
4. Copy the Application ID.
5. Invite the bot with:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Embed Links`, `Attach Files`, `Use External Emojis`, `Read Message History`
6. Create a private Discord channel for generated image assets.
7. Give the bot View Channel, Send Messages, Attach Files, and Read Message History in that channel.
8. Copy that channel ID for `DISCORD_ASSET_CHANNEL_ID`.
9. Copy your staff role ID for `DISCORD_STAFF_ROLE_ID`, if staff commands should be role-gated.

## 2. Prepare DNS And Nginx

The bot itself does not need an inbound public HTTP endpoint. If this server already has Nginx, keep using it for your normal website. If you want a simple operational endpoint for the box, create a static health URL.

Install Nginx and Certbot:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create `/etc/nginx/sites-available/dungeon-steward`:

```nginx
server {
    listen 80;
    server_name dungeon.example.com;

    location = /healthz {
        add_header Content-Type text/plain;
        return 200 "ok\n";
    }

    location / {
        add_header Content-Type text/plain;
        return 200 "Dungeon Steward bot host\n";
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/dungeon-steward /etc/nginx/sites-enabled/dungeon-steward
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d dungeon.example.com
```

Do not set a Discord Interactions Endpoint URL for this bot. `discord.py` registers slash commands and receives interactions over the bot gateway connection.

If you use a restrictive outbound firewall, allow HTTPS to Discord:

```text
discord.com:443
gateway.discord.gg:443
cdn.discordapp.com:443
media.discordapp.net:443
```

## 3. Install System Packages

```bash
sudo apt update
sudo apt install -y git python3.12 python3.12-venv python3-pip postgresql postgresql-contrib libpq-dev
```

If your Ubuntu release does not provide Python 3.12, install it from your normal Python package source before continuing.

## 4. Create The App User

```bash
sudo useradd --system --home /var/www/kellrond-discord-bot --shell /usr/sbin/nologin kellrond-bot
sudo mkdir -p /var/www/kellrond-discord-bot
sudo chown -R kellrond-bot:kellrond-bot /var/www/kellrond-discord-bot
```

## 5. Install The App

Clone or copy the repository into `/var/www/kellrond-discord-bot`:

```bash
sudo -u kellrond-bot git clone https://github.com/JPKell/dungeon-steward.git /var/www/kellrond-discord-bot
cd /var/www/kellrond-discord-bot
sudo -u kellrond-bot python3.12 -m venv .venv
sudo -u kellrond-bot .venv/bin/pip install --upgrade pip
sudo -u kellrond-bot .venv/bin/pip install -r requirements.txt
```

If you deploy by copying files instead of cloning, make sure the final owner is still `kellrond-bot:kellrond-bot`.

## 6. Create PostgreSQL Database

Generate a strong password:

```bash
openssl rand -base64 32
```

Create the role and database:

```bash
sudo -u postgres createuser --pwprompt kellrond_bot
sudo -u postgres createdb --owner=kellrond_bot kellrond_discord_bot
```

Verify login:

```bash
psql "postgresql://kellrond_bot:<password>@localhost:5432/kellrond_discord_bot" -c "select current_database(), current_user;"
```

The app uses SQLAlchemy's psycopg driver, so the production URL will use this shape:

```text
postgresql+psycopg://kellrond_bot:<password>@localhost:5432/kellrond_discord_bot
```

## 7. Create Production Environment File

Create `/etc/kellrond-bot.env`:

```dotenv
ENVIRONMENT=production
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://kellrond_bot:<password>@localhost:5432/kellrond_discord_bot
DISCORD_BOT_TOKEN=<bot-token>
DISCORD_APPLICATION_ID=<application-id>
DISCORD_TEST_GUILD_ID=
DISCORD_STAFF_ROLE_ID=<staff-role-id>
DISCORD_ASSET_CHANNEL_ID=<private-asset-channel-id>
DUNGEON_ADMIN_IDENTITIES=
DUNGEON_ADMIN_IDENTITY=
DUNGEON_ADMIN_PAGE_SIZE=50
DUNGEON_ADMIN_STATEMENT_TIMEOUT_MS=
```

Lock it down:

```bash
sudo chown root:kellrond-bot /etc/kellrond-bot.env
sudo chmod 640 /etc/kellrond-bot.env
```

For first launch in one test server, temporarily set `DISCORD_TEST_GUILD_ID=<guild-id>`. For real production global commands, leave it empty. Global command updates can take longer to appear in Discord.

## 8. Run Migrations And Load Content

```bash
cd /var/www/kellrond-discord-bot
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/alembic upgrade head'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.content_db load'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.validate_content'
```

The `source` step keeps passwords with punctuation intact. If you prefer an interactive shell, run commands from a root shell after exporting the env file instead:

```bash
sudo -iu root
set -a
. /etc/kellrond-bot.env
set +a
cd /var/www/kellrond-discord-bot
sudo -u kellrond-bot -E .venv/bin/alembic upgrade head
sudo -u kellrond-bot -E .venv/bin/python -m scripts.content_db load
sudo -u kellrond-bot -E .venv/bin/python -m scripts.validate_content
exit
```

## 9. Cache Images And Emojis On Discord

This project has two Discord visual asset registries:

- Image banners/thumbnails upload to the private asset channel and store Discord CDN URLs in `bot/content/image_asset_registry.json`.
- Application emojis upload to the Discord application and store emoji IDs in `bot/content/emoji_asset_registry.json`.

Run a safe dry run first:

```bash
cd /var/www/kellrond-discord-bot
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets --prepare-only'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets --dry-run'
```

Then upload and write the registries:

```bash
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets'
```

Review changed registry files and keep them with your deployed code. The runtime bot reads those registries so embeds can use Discord CDN URLs and inline custom emoji IDs without attaching local files to every message.

Useful targeted syncs:

```bash
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets --prefix location.'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets --prefix equipment. --emojis-only'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets --emojis-only'
```

See `docs/DISCORD_IMAGES.md` for asset sizes, source paths, and replacement flow.

## 10. Install systemd Service

```bash
cd /var/www/kellrond-discord-bot
sudo cp deploy/kellrond-discord-bot.service /etc/systemd/system/kellrond-discord-bot.service
sudo systemctl daemon-reload
sudo systemctl enable kellrond-discord-bot
sudo systemctl start kellrond-discord-bot
```

Check it:

```bash
sudo systemctl status kellrond-discord-bot
sudo journalctl -u kellrond-discord-bot -f
```

## 11. Verify In Discord

1. Confirm the bot appears online.
2. Run `/dungeon hall`.
3. Run `/dungeon profile`.
4. Run `/dungeon shop` and verify equipment emojis/images render.
5. Run a staff-only command, such as `/dungeon-admin event-status`, from an authorized account.
6. Check logs for startup content loading and command sync:

```bash
sudo journalctl -u kellrond-discord-bot -n 200 --no-pager
```

If commands do not appear:

- With `DISCORD_TEST_GUILD_ID` set, restart the bot and check that guild.
- With global commands, wait for Discord propagation.
- Confirm the OAuth2 install included `applications.commands`.

## 12. Backups

Create a backup directory outside the app tree:

```bash
sudo mkdir -p /var/backups/kellrond-discord-bot
sudo chmod 700 /var/backups/kellrond-discord-bot
```

Manual backup:

```bash
sudo -u postgres pg_dump --format=custom --file=/var/backups/kellrond-discord-bot/kellrond_discord_bot-$(date +%F).dump kellrond_discord_bot
```

Test restore procedures periodically on a separate database. Do not wait for an emergency to discover that backups are decorative.

## 13. Update Procedure

```bash
cd /var/www/kellrond-discord-bot
sudo systemctl stop kellrond-discord-bot
sudo -u kellrond-bot git pull
sudo -u kellrond-bot .venv/bin/pip install -r requirements.txt
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/alembic upgrade head'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.content_db load'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets --dry-run'
sudo -u kellrond-bot bash -lc 'set -a; source /etc/kellrond-bot.env; set +a; cd /var/www/kellrond-discord-bot; .venv/bin/python -m scripts.sync_assets'
sudo systemctl start kellrond-discord-bot
sudo systemctl status kellrond-discord-bot
```

If the asset registry files changed during `sync_assets`, commit or otherwise preserve them in your deployment source.

## 14. Token Rotation

1. Regenerate the bot token in the Discord Developer Portal.
2. Update `DISCORD_BOT_TOKEN` in `/etc/kellrond-bot.env`.
3. Restart:

```bash
sudo systemctl restart kellrond-discord-bot
```

## 15. Troubleshooting

- **Bot does not start:** check `DISCORD_BOT_TOKEN`, `DATABASE_URL`, and `journalctl -u kellrond-discord-bot`.
- **Database errors:** run `sudo -u kellrond-bot -E .venv/bin/alembic current` with the production environment loaded.
- **Content load fails:** run `.venv/bin/python -m scripts.validate_content`.
- **Images are attachments instead of CDN URLs:** run `scripts.sync_assets` and confirm `image_asset_registry.json` has entries.
- **Custom emojis show as text or missing icons:** run `scripts.sync_assets --emojis-only` and confirm the application ID is correct.
- **Slash commands are missing:** verify the OAuth2 install scopes and whether you are using guild or global command sync.
- **Nginx works but bot does not:** Nginx is unrelated to slash-command delivery. Check the systemd service and Discord connection logs.
