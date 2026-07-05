from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord

from bot.config import load_settings
from bot.services.discord_asset_service import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_REGISTRY_PATH,
    AssetCatalog,
    AssetDefinition,
    AssetRegistry,
    ImageInfo,
    load_catalog,
    load_registry,
    registry_asset_from_upload,
    validate_asset_file,
    write_registry_atomic,
)


@dataclass(frozen=True)
class PlannedAsset:
    definition: AssetDefinition
    image: ImageInfo | None
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
    parser = argparse.ArgumentParser(description="Upload prepared Discord image assets and write the CDN registry.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the upload plan without connecting to Discord.")
    parser.add_argument("--key", help="Synchronize one logical asset key.")
    parser.add_argument("--prefix", help="Synchronize all keys under a prefix.")
    parser.add_argument("--prune", action="store_true", help="Reserved for deliberate cleanup; never runs implicitly.")
    args = parser.parse_args()

    if args.prune:
        raise SystemExit("--prune is intentionally not automatic. Delete old Discord asset messages manually after review.")

    catalog = load_catalog(args.catalog)
    registry = load_registry(args.registry)
    planned, summary = plan_sync(catalog, registry, key=args.key, prefix=args.prefix)
    for item in planned:
        suffix = f" ({item.error})" if item.error else ""
        print(f"{item.action.upper()} {item.definition.key}{suffix}")
    if args.dry_run:
        print(f"Summary: {summary.as_dict()}")
        if summary.failed or summary.missing:
            raise SystemExit(1)
        return

    settings = load_settings(require_token=True)
    if settings.discord_asset_channel_id is None:
        raise SystemExit("DISCORD_ASSET_CHANNEL_ID is required to synchronize Discord assets.")
    if summary.failed or summary.missing:
        raise SystemExit(f"Local asset validation failed: {summary.as_dict()}")
    asyncio.run(_sync_with_discord(settings.discord_bot_token, settings.discord_asset_channel_id, planned, registry, args.registry))


def plan_sync(
    catalog: AssetCatalog,
    registry: AssetRegistry,
    *,
    key: str | None = None,
    prefix: str | None = None,
) -> tuple[list[PlannedAsset], SyncSummary]:
    if key and prefix:
        raise ValueError("Use --key or --prefix, not both.")
    definitions = _filtered_assets(catalog, key=key, prefix=prefix)
    planned: list[PlannedAsset] = []
    summary = SyncSummary()
    for definition in definitions:
        try:
            validation = validate_asset_file(definition)
        except Exception as exc:
            action = "missing" if not definition.path.exists() else "failed"
            if action == "missing":
                summary.missing += 1
            else:
                summary.failed += 1
            planned.append(PlannedAsset(definition=definition, image=None, action=action, error=str(exc)))
            continue

        existing = registry.get(definition.key)
        if existing and existing.sha256 == validation.image.sha256:
            summary.unchanged += 1
            planned.append(PlannedAsset(definition=definition, image=validation.image, action="unchanged"))
        elif existing:
            summary.updated += 1
            planned.append(PlannedAsset(definition=definition, image=validation.image, action="updated"))
        else:
            summary.uploaded += 1
            planned.append(PlannedAsset(definition=definition, image=validation.image, action="uploaded"))
    return planned, summary


async def sync_registry_with_channel(
    channel: Any,
    planned: list[PlannedAsset],
    registry: AssetRegistry,
) -> AssetRegistry:
    assets = dict(registry.assets)
    for item in planned:
        if item.action == "unchanged":
            continue
        if item.action in {"missing", "failed"}:
            raise RuntimeError(f"Cannot upload invalid asset {item.definition.key}: {item.error}")
        if item.image is None:
            raise RuntimeError(f"Cannot upload asset without image metadata: {item.definition.key}")
        message = await channel.send(
            content=build_asset_message(item.definition, item.image),
            file=discord.File(item.definition.path, filename=item.definition.filename),
        )
        if not message.attachments:
            raise RuntimeError(f"Discord did not return an attachment for {item.definition.key}")
        attachment = message.attachments[0]
        assets[item.definition.key] = registry_asset_from_upload(
            key=item.definition.key,
            definition=item.definition,
            image=item.image,
            channel_id=channel.id,
            message_id=message.id,
            attachment_id=attachment.id,
            cdn_url=str(attachment.url),
        )
    return AssetRegistry(version=registry.version, assets=assets)


def build_asset_message(definition: AssetDefinition, image: ImageInfo) -> str:
    return (
        "Dungeon Steward static asset\n"
        f"Key: {definition.key}\n"
        f"Type: {definition.type}\n"
        f"SHA-256: {image.sha256}\n"
        f"Dimensions: {image.width}x{image.height}"
    )


def validate_channel_permissions(channel: Any, actor: Any) -> None:
    permissions_for = getattr(channel, "permissions_for", None)
    if permissions_for is None:
        return
    permissions = permissions_for(actor)
    required = ("view_channel", "send_messages", "attach_files", "read_message_history")
    missing = [name for name in required if not getattr(permissions, name, False)]
    if missing:
        raise RuntimeError(f"Asset channel is missing permissions: {', '.join(missing)}")


async def _sync_with_discord(
    token: str,
    channel_id: int,
    planned: list[PlannedAsset],
    registry: AssetRegistry,
    registry_path: Path,
) -> None:
    client = _AssetSyncClient(channel_id=channel_id, planned=planned, registry=registry, registry_path=registry_path)
    try:
        await client.start(token)
    finally:
        if not client.is_closed():
            await client.close()


class _AssetSyncClient(discord.Client):
    def __init__(
        self,
        *,
        channel_id: int,
        planned: list[PlannedAsset],
        registry: AssetRegistry,
        registry_path: Path,
    ) -> None:
        super().__init__(intents=discord.Intents.none())
        self.channel_id = channel_id
        self.planned = planned
        self.registry = registry
        self.registry_path = registry_path

    async def on_ready(self) -> None:
        try:
            channel = self.get_channel(self.channel_id) or await self.fetch_channel(self.channel_id)
            validate_channel_permissions(channel, getattr(channel.guild, "me", None) or self.user)
            updated_registry = await sync_registry_with_channel(channel, self.planned, self.registry)
            write_registry_atomic(updated_registry, self.registry_path)
            uploaded_count = sum(1 for item in self.planned if item.action in {"uploaded", "updated"})
            unchanged_count = sum(1 for item in self.planned if item.action == "unchanged")
            print(f"Summary: uploaded_or_updated={uploaded_count} unchanged={unchanged_count}")
        finally:
            await self.close()


def _filtered_assets(catalog: AssetCatalog, *, key: str | None, prefix: str | None) -> list[AssetDefinition]:
    if key:
        return [catalog.get(key)]
    if prefix:
        return [definition for asset_key, definition in sorted(catalog.assets.items()) if asset_key.startswith(prefix)]
    return [definition for _, definition in sorted(catalog.assets.items())]


if __name__ == "__main__":
    main()
