# Discord Visual Assets

Dungeon Steward has two Discord visual asset pipelines:

- **Images** are embed banners or thumbnails. They are uploaded to a private Discord asset channel and then used by CDN URL.
- **Emojis** are inline application emojis. They are uploaded to the Discord application and then used by emoji ID.

Run one command after adding or replacing assets:

```bash
.venv/bin/python -m scripts.sync_assets --prepare-only
.venv/bin/python -m scripts.sync_assets --dry-run
.venv/bin/python -m scripts.sync_assets
```

For new or changed source art, `--prepare-only` creates the local prepared image files and validates them without touching Discord. `--dry-run` validates existing prepared files and prints the upload plan without uploading to Discord or writing registries. The real run prepares changed source images, validates both pipelines, uploads changed images/emojis, and writes generated registry JSON.

## Files

```text
assets/
  discord/
    source/                 # Original art in whatever size you have it
      banners/              # Location banner originals
      enemies/              # Enemy originals used for thumbnails and emojis
      equipment/            # Equipment originals named slot_type.png
      potions/              # Potion originals named shorttype_01.png
    locations/              # Prepared 1200x244 banner outputs
    thumbnails/             # Prepared 256x256 image thumbnail outputs
    emojis/                 # Prepared 128x128 emoji image outputs
bot/content/
  image_assets.json         # Image catalog you edit
  image_asset_registry.json # Generated Discord CDN image registry
  emoji_assets.json         # Emoji catalog you edit
  emoji_asset_registry.json # Generated application emoji ID registry
```

You do need the four JSON files:

- `image_assets.json`: the source of truth for image assets the bot can put in embeds.
- `image_asset_registry.json`: generated after image sync; runtime uses this to send Discord CDN URLs.
- `emoji_assets.json`: the source of truth for application emojis.
- `emoji_asset_registry.json`: generated after emoji sync; runtime uses this to render custom emoji markup.

Do not hand-edit either registry unless you are repairing a known bad sync. The old `.bak` registry file was only a sync backup and is not part of the pipeline.

`alt_text` and `required` are optional in catalog entries. If you omit `alt_text`, the loader derives a readable fallback from the key or emoji name. If you omit `required`, it defaults to `false`. Use `required: true` only for assets that should make production validation fail when they are not registered.

## Runtime Behavior

For banners, the bot now prefers `image_asset_registry.json`. If a registry entry exists, the embed image URL is Discord's CDN URL and no local file is attached to the player-facing message.

In development only, if an image has no registry entry but the prepared local file exists, the bot falls back to an `attachment://...` local file. In production, required images should be synced before the bot runs.

Potion icons use the same logical key in both catalogs: `image_assets.json` for embed thumbnails and `emoji_assets.json` for inline custom emojis. The potion content still uses the field name `thumbnail_asset`; those keys validate against both catalogs.

## Standards

| Type | Use | Size | Preferred Format | Warning | Hard Limit |
| --- | --- | --- | --- | --- | --- |
| `location_banner` | Command and location banners | `1200x244` | WebP | 500 KB | 750 KB |
| `thumbnail` | Optional item/equipment thumbnails | `256x256` | WebP or PNG | 150 KB | 250 KB |
| `encounter_artwork` | Optional full encounter art | `1200x675` | WebP | 750 KB | 1 MB |
| application emoji | Inline potion/item markers | `128x128` | PNG or JPEG | n/a | 256 KB |

Keep important banner labels and symbols on the left half of source artwork; banner preparation preserves the left edge when cropping wide sources.

## Environment

Set these before running the real sync:

```env
DISCORD_BOT_TOKEN=
DISCORD_ASSET_CHANNEL_ID=
DISCORD_APPLICATION_ID=
```

The asset channel should be private and visible to maintainers and the bot. The bot needs View Channel, Send Messages, Attach Files, and Read Message History.

## Source Folder Rules

The source folder is the only place you keep original art. The sync script never resizes source files in place; it writes prepared outputs to `assets/discord/locations`, `assets/discord/thumbnails`, and `assets/discord/emojis`.

- Banners: put originals in `assets/discord/source/banners/<location_key>.png`; catalog key is `location.<location_key>`.
- Enemies: put originals in `assets/discord/source/enemies/<enemy_key>.png`; each one is both an image thumbnail `enemy.<enemy_key>` and an emoji `enemy.<enemy_key>`.
- Equipment: put originals in `assets/discord/source/equipment/<slot>_<type>.png`; catalog key is `equipment.<slot>_<type>`, and equipment records store that key in `thumbnail_asset`.
- Potions: put originals in `assets/discord/source/potions/<short_type>_<tier>.png`; each one is both an image thumbnail and an emoji. Current short types are `atk`, `def`, `healing`, `hp`, `luck`, and `xp`.

Catalog entries only need `type`, `path`, and `source_path` for images, or `name`, `path`, and `source_path` for emojis. `alt_text` and `required` are optional.

## Add Or Replace A Banner

1. Put original art in `assets/discord/source/banners/`, for example `assets/discord/source/banners/arena.png`.
2. Add or update an entry in `bot/content/image_assets.json`:

```json
"location.arena": {
  "type": "location_banner",
  "path": "assets/discord/locations/arena.webp",
  "source_path": "assets/discord/source/banners/arena.png"
}
```

3. Reference the key from content, usually in `bot/content/locations.json`.
4. Run:

```bash
.venv/bin/python -m scripts.sync_assets --prepare-only --key location.arena
.venv/bin/python -m scripts.sync_assets --dry-run --key location.arena
.venv/bin/python -m scripts.sync_assets --key location.arena
```

The script creates `assets/discord/locations/arena.webp` at `1200x300`, uploads it to Discord, and updates `image_asset_registry.json`.

## Add Or Replace An Emoji

1. Put original art in the matching `assets/discord/source/` subfolder, for example `assets/discord/source/enemies/slime.png`.
2. Add or update an entry in `bot/content/emoji_assets.json`:

```json
"enemy.slime": {
  "name": "ds_e_slime",
  "path": "assets/discord/emojis/enemies/slime.png",
  "source_path": "assets/discord/source/enemies/slime.png"
}
```

3. Reference the logical key from content or code.
4. Run:

```bash
.venv/bin/python -m scripts.sync_assets --prepare-only --key item.rune.01
.venv/bin/python -m scripts.sync_assets --dry-run --key item.rune.01
.venv/bin/python -m scripts.sync_assets --key item.rune.01
```

The script creates the prepared emoji at `128x128`, uploads it to the Discord application, and updates `emoji_asset_registry.json`. Emoji names must be 2-32 letters, numbers, or underscores. Keep the `ds_` prefix so application emojis remain easy to identify in Discord.

For enemies and potions that should also have an embed thumbnail, add the matching entry to `bot/content/image_assets.json` too:

```json
"enemy.slime": {
  "type": "thumbnail",
  "path": "assets/discord/thumbnails/enemies/slime.webp",
  "source_path": "assets/discord/source/enemies/slime.png"
}
```

Equipment emojis are generated from `equipment.*` entries in `bot/content/image_assets.json`. The generated emoji output path is
`assets/discord/emojis/equipment/<equipment_slug>.png`, and the application emoji name is `ds_eq_<equipment_slug>`.
Run:

```bash
.venv/bin/python -m scripts.sync_assets --prepare-only --prefix equipment. --emojis-only
.venv/bin/python -m scripts.sync_assets --dry-run --prefix equipment. --emojis-only
.venv/bin/python -m scripts.sync_assets --prefix equipment. --emojis-only
```

Then point the content record at those keys, for example `thumbnail_asset: "enemy.slime"` and `emoji_asset: "enemy.slime"` in `bot/content/enemies.json`.

## Useful Filters

```bash
.venv/bin/python -m scripts.sync_assets --prepare-only --prefix location.
.venv/bin/python -m scripts.sync_assets --images-only
.venv/bin/python -m scripts.sync_assets --emojis-only
.venv/bin/python -m scripts.sync_assets --prefix location.
.venv/bin/python -m scripts.sync_assets --prefix item.potion --emojis-only
```

## Validation

Use the normal content and test checks after asset changes:

```bash
.venv/bin/python -m scripts.validate_content
.venv/bin/python -m pytest
```
