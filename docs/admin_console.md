# Dungeon Steward Admin Console

The admin console is a curses-based terminal tool for support and database administration over SSH.

## Install

Use the normal project environment:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```

No extra runtime dependency is required; the console uses Python's standard `curses` module.

## Administrator Access

The console requires an explicit administrator identity. Configure allowed administrators with:

```dotenv
DUNGEON_ADMIN_IDENTITIES=alice:super_admin,bob:game_support,readbot:read_only
DUNGEON_ADMIN_IDENTITY=alice
```

Supported roles are:

- `read_only`
- `game_support`
- `database_admin`
- `super_admin`

An identity not listed in `DUNGEON_ADMIN_IDENTITIES` is refused, even when the user has SSH access.

## Launch

Development:

```bash
python -m dungeon_steward_admin --environment development --admin alice
```

Read-only production:

```bash
python -m dungeon_steward_admin --environment production --read-only --admin readbot
```

Production writes require a startup confirmation phrase:

```bash
python -m dungeon_steward_admin --environment production --admin alice
```

The console prompts for `PRODUCTION` before it will enable writes.

Direct user lookup:

```bash
python -m dungeon_steward_admin --user 123456789 --admin alice
```

## Configuration

Database settings are loaded through the existing project configuration:

```dotenv
DATABASE_URL=sqlite:///./dungeon_steward.sqlite3
ENVIRONMENT=development
DUNGEON_ADMIN_PAGE_SIZE=50
DUNGEON_ADMIN_STATEMENT_TIMEOUT_MS=5000
```

Database passwords are never displayed in the interface; SQLAlchemy renders the database URL with passwords hidden.

## Navigation

- Arrow keys: move
- Page Up / Page Down: page
- Home / End: jump
- Enter: select
- `q` or Escape: go back
- `?`: show help

Every screen displays the active environment and read/write mode in the header.

## User Administration

User search supports:

- Internal player ID
- Discord user ID
- Guild ID
- Display name and partial display-name matches

The selected user screen shows only fields that exist in the project: Discord ID, guild ID, levels, HP, gold, active defense, active potion effects, potion inventory quantity, and equipped slot count.

## Inventory And Equipment

Potion administration uses the authoritative potion content and `PotionService` validation.

Supported operations:

- Set exact potion stack quantity
- Adjust potion quantity by a positive or negative delta
- End an active potion effect

Equipment administration uses the authoritative `EquipmentService` catalogue.

Supported operations:

- Equip a catalogue item into its slot
- Unequip a slot
- Remove an equipped item only with explicit confirmation in the backend API

The current game schema stores equipped equipment on the player record rather than as duplicate ownership rows, so quantity changes are not exposed for equipment.

## Generic Table CRUD

The table browser discovers SQLAlchemy models from `Base.registry`.

It supports:

- Paginated listing
- Search against configured fields
- Create records from JSON field values
- Edit individual fields
- Delete or soft-delete records

Protected fields are not editable by default:

- Primary keys
- `created_at`
- `updated_at`
- Hidden fields configured in the registry

Tables can be configured with:

```python
from dungeon_steward_admin.registry import register_admin_model

register_admin_model(
    MyModel,
    searchable_fields=["name"],
    readonly_fields=["id", "created_at", "updated_at"],
    hidden_fields=["token"],
    display_fields=["id", "name"],
    read_only=False,
    permission="database_admin",
)
```

Ordinary new SQLAlchemy models appear automatically. Add a registry override only when the table needs special fields, permissions, read-only behavior, or validators.

## Custom Actions

Feature-specific actions are registered with:

```python
from dungeon_steward_admin.actions import ActionResult, admin_action

@admin_action(
    name="Repair Inventory",
    target="user",
    permission="game_support",
    requires_confirmation=True,
)
def repair_inventory(context, session, values):
    ...
    return ActionResult(True, "Inventory repaired.")
```

Built-in actions include:

- Grant Gold
- Grant Combat XP
- Reset Active Defense
- Recalculate Combat Progression
- End Potion Effect

All write actions run in a transaction and write an audit entry.

## Audit Logging

Alembic migration `20260703_0004_admin_audit_log` adds `admin_audit_log`.

Each write records:

- Administrator identity and role
- Environment
- Action name
- Target domain/table/user/record
- Previous and new values
- Quantity changed
- Reason
- Result
- Admin console session ID

Sensitive fields containing `password`, `token`, `secret`, `credential`, or `api_key` are redacted.

## Recovery

The console uses `curses.wrapper`, so Ctrl+C or unexpected exceptions restore the terminal state. If an operation fails, the active SQLAlchemy transaction is rolled back and the error is displayed without showing database secrets.

## Production Safety

- Prefer `--read-only` for investigation.
- Use production writes only with a named administrator identity.
- Always provide a reason for support changes.
- Run `alembic upgrade head` before launching after updates.
- Keep `DUNGEON_ADMIN_IDENTITIES` in server environment configuration, not source control.
