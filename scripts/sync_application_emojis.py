from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

import discord

from bot.config import load_settings
from bot.services.discord_emoji_service import (
    DEFAULT_EMOJI_CATALOG_PATH,
    DEFAULT_EMOJI_REGISTRY_PATH,
    EmojiCatalog,
    EmojiDefinition,
    EmojiRegistry,
    emoji_entry_from_upload,
    load_emoji_catalog,
    load_emoji_registry,
    sha256_file,
    validate_emoji_file,
    write_emoji_registry_atomic,
)


@dataclass(frozen=True)
class PlannedEmoji:
    definition: EmojiDefinition
    sha256: str | None
    action: str
    error: str | None = None


@dataclass
class SyncSummary:
    uploaded: int = 0
    unchanged: int = 0
    updated: int = 0
    missing: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "uploaded": self.uploaded,
            "unchanged": self.unchanged,
            "updated": self.updated,
            "missing": self.missing,
            "failed": self.failed,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Dungeon Steward application emojis and write the emoji registry.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_EMOJI_CATALOG_PATH)
    parser.add_argument("--registry", type=Path, default=DEFAULT_EMOJI_REGISTRY_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the upload plan without connecting to Discord.")
    parser.add_argument("--key", help="Synchronize one logical emoji key.")
    parser.add_argument("--prefix", help="Synchronize all keys under a prefix.")
    args = parser.parse_args()

    catalog = load_emoji_catalog(args.catalog)
    registry = load_emoji_registry(args.registry)
    planned, summary = plan_sync(catalog, registry, key=args.key, prefix=args.prefix)
    for item in planned:
        suffix = f" ({item.error})" if item.error else ""
        print(f"{item.action.upper()} {item.definition.key} -> {item.definition.name}{suffix}")
    if args.dry_run:
        print(f"Summary: {summary.as_dict()}")
        if summary.failed or summary.missing:
            raise SystemExit(1)
        return

    settings = load_settings(require_token=True)
    if settings.discord_application_id is None:
        raise SystemExit("DISCORD_APPLICATION_ID is required to synchronize application emojis.")
    if summary.failed or summary.missing:
        raise SystemExit(f"Local emoji validation failed: {summary.as_dict()}")

    asyncio.run(
        _sync_with_discord(
            token=settings.discord_bot_token,
            application_id=settings.discord_application_id,
            planned=planned,
            registry=registry,
            registry_path=args.registry,
        )
    )


def plan_sync(
    catalog: EmojiCatalog,
    registry: EmojiRegistry,
    *,
    key: str | None = None,
    prefix: str | None = None,
) -> tuple[list[PlannedEmoji], SyncSummary]:
    if key and prefix:
        raise ValueError("Use --key or --prefix, not both.")
    definitions = _filtered_emojis(catalog, key=key, prefix=prefix)
    planned: list[PlannedEmoji] = []
    summary = SyncSummary()
    for definition in definitions:
        try:
            validate_emoji_file(definition)
            sha256 = sha256_file(definition.path)
        except Exception as exc:
            action = "missing" if not definition.path.exists() else "failed"
            if action == "missing":
                summary.missing += 1
            else:
                summary.failed += 1
            planned.append(PlannedEmoji(definition=definition, sha256=None, action=action, error=str(exc)))
            continue

        existing = registry.get(definition.key)
        if existing and existing.sha256 == sha256 and existing.name == definition.name:
            summary.unchanged += 1
            planned.append(PlannedEmoji(definition=definition, sha256=sha256, action="unchanged"))
        elif existing:
            summary.updated += 1
            planned.append(PlannedEmoji(definition=definition, sha256=sha256, action="updated"))
        else:
            summary.uploaded += 1
            planned.append(PlannedEmoji(definition=definition, sha256=sha256, action="uploaded"))
    return planned, summary


async def sync_registry_with_client(
    client: discord.Client,
    planned: list[PlannedEmoji],
    registry: EmojiRegistry,
) -> EmojiRegistry:
    existing = await client.fetch_application_emojis()
    existing_by_id = {str(emoji.id): emoji for emoji in existing}
    existing_by_name = {emoji.name: emoji for emoji in existing}
    entries = dict(registry.emojis)

    for item in planned:
        if item.action in {"missing", "failed"}:
            raise RuntimeError(f"Cannot upload invalid emoji {item.definition.key}: {item.error}")
        if item.sha256 is None:
            raise RuntimeError(f"Cannot upload emoji without image metadata: {item.definition.key}")

        registry_entry = registry.get(item.definition.key)
        current = existing_by_id.get(registry_entry.emoji_id) if registry_entry else None
        if item.action == "unchanged" and current is not None:
            continue
        if item.action == "unchanged" and item.definition.name in existing_by_name:
            emoji = existing_by_name[item.definition.name]
            entries[item.definition.key] = emoji_entry_from_upload(
                key=item.definition.key,
                definition=item.definition,
                emoji_id=emoji.id,
                sha256=item.sha256,
                animated=bool(getattr(emoji, "animated", False)),
            )
            continue

        if current is not None:
            await current.delete()
        elif item.definition.name in existing_by_name:
            await existing_by_name[item.definition.name].delete()

        emoji = await client.create_application_emoji(name=item.definition.name, image=item.definition.path.read_bytes())
        entries[item.definition.key] = emoji_entry_from_upload(
            key=item.definition.key,
            definition=item.definition,
            emoji_id=emoji.id,
            sha256=item.sha256,
            animated=bool(getattr(emoji, "animated", False)),
        )
        existing_by_id[str(emoji.id)] = emoji
        existing_by_name[item.definition.name] = emoji

    return EmojiRegistry(version=registry.version, emojis=entries)


async def _sync_with_discord(
    *,
    token: str,
    application_id: int,
    planned: list[PlannedEmoji],
    registry: EmojiRegistry,
    registry_path: Path,
) -> None:
    client = _EmojiSyncClient(
        application_id=application_id,
        planned=planned,
        registry=registry,
        registry_path=registry_path,
    )
    try:
        await client.start(token)
    finally:
        if not client.is_closed():
            await client.close()


class _EmojiSyncClient(discord.Client):
    def __init__(
        self,
        *,
        application_id: int,
        planned: list[PlannedEmoji],
        registry: EmojiRegistry,
        registry_path: Path,
    ) -> None:
        super().__init__(intents=discord.Intents.none(), application_id=application_id)
        self.planned = planned
        self.registry = registry
        self.registry_path = registry_path

    async def on_ready(self) -> None:
        try:
            updated_registry = await sync_registry_with_client(self, self.planned, self.registry)
            write_emoji_registry_atomic(updated_registry, self.registry_path)
            uploaded_count = sum(1 for item in self.planned if item.action in {"uploaded", "updated"})
            unchanged_count = sum(1 for item in self.planned if item.action == "unchanged")
            print(f"Summary: uploaded_or_updated={uploaded_count} unchanged={unchanged_count}")
        finally:
            await self.close()


def _filtered_emojis(
    catalog: EmojiCatalog,
    *,
    key: str | None,
    prefix: str | None,
) -> list[EmojiDefinition]:
    if key:
        try:
            return [catalog.emojis[key]]
        except KeyError as error:
            raise ValueError(f"Unknown emoji key: {key}") from error
    if prefix:
        return [definition for emoji_key, definition in sorted(catalog.emojis.items()) if emoji_key.startswith(prefix)]
    return [definition for _, definition in sorted(catalog.emojis.items())]


if __name__ == "__main__":
    main()
