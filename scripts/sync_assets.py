"""Prepare, validate, and synchronize all Discord-facing visual assets.

This is the one command to run after adding or replacing files under
``assets/discord``. It handles the two separate Discord asset systems:

* Images: source art is prepared into fixed-size files, then uploaded to a
  private Discord asset channel. Runtime embeds use the generated CDN registry.
* Emojis: 128x128 PNG/JPEG files are uploaded as application emojis. Runtime
  text uses the generated emoji ID registry.

Useful commands:

    .venv/bin/python -m scripts.sync_assets --prepare-only --key location.shop
    .venv/bin/python -m scripts.sync_assets --dry-run
    .venv/bin/python -m scripts.sync_assets
    .venv/bin/python -m scripts.sync_assets --key location.shop
    .venv/bin/python -m scripts.sync_assets --prefix item.potion --emojis-only
    .venv/bin/python -m scripts.sync_assets --prefix equipment. --emojis-only
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
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
    AssetValidationError,
    ImageInfo,
    inspect_image_file,
    load_catalog,
    load_registry,
    registry_asset_from_upload,
    validate_asset_file,
    write_registry_atomic,
)
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
    validate_emoji_asset_references,
    validate_emoji_file,
    write_emoji_registry_atomic,
)


@dataclass(frozen=True)
class PlannedImageAsset:
    definition: AssetDefinition
    image: ImageInfo | None
    action: str
    error: str | None = None


@dataclass
class ImageSyncSummary:
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


@dataclass(frozen=True)
class PlannedEmoji:
    definition: EmojiDefinition
    sha256: str | None
    action: str
    error: str | None = None


@dataclass
class EmojiSyncSummary:
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
    parser = argparse.ArgumentParser(
        description="Prepare, validate, and synchronize Dungeon Steward Discord images and application emojis."
    )
    parser.add_argument("--image-catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--image-registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--emoji-catalog", type=Path, default=DEFAULT_EMOJI_CATALOG_PATH)
    parser.add_argument("--emoji-registry", type=Path, default=DEFAULT_EMOJI_REGISTRY_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print sync plans without writing files or Discord state.")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare and validate local outputs, then exit before Discord sync.",
    )
    parser.add_argument("--skip-prepare", action="store_true", help="Do not regenerate prepared outputs before validation.")
    parser.add_argument("--quality", type=int, default=82, help="WebP quality for prepared photographic artwork.")
    parser.add_argument("--key", help="Process one logical image or emoji key.")
    parser.add_argument("--prefix", help="Process keys under one logical prefix.")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--images-only", action="store_true", help="Process only Discord channel image assets.")
    scope.add_argument("--emojis-only", action="store_true", help="Process only application emoji assets.")
    args = parser.parse_args()

    if args.key and args.prefix:
        raise SystemExit("Use --key or --prefix, not both.")
    if args.dry_run and args.prepare_only:
        raise SystemExit("Use --dry-run or --prepare-only, not both.")

    run_images = not args.emojis_only
    run_emojis = not args.images_only
    any_matches = False
    had_errors = False

    image_catalog = image_registry = None
    image_plan: list[PlannedImageAsset] = []
    if run_images:
        image_catalog = load_catalog(args.image_catalog)
        image_registry = load_registry(args.image_registry)
        image_definitions = _filtered_image_assets(image_catalog, key=args.key, prefix=args.prefix, strict=False)
        any_matches = any_matches or bool(image_definitions)
        if image_definitions:
            if args.dry_run:
                print("Image prepare: skipped for --dry-run")
            elif args.skip_prepare:
                print("Image prepare: skipped by --skip-prepare")
            else:
                prepare_image_assets(image_definitions, quality=args.quality)
            image_plan, image_summary = plan_image_definitions(image_definitions, image_registry)
            _print_image_plan(image_plan, image_summary)
            had_errors = had_errors or bool(image_summary.failed or image_summary.missing)
        else:
            print("Image assets: no matching keys")

    emoji_catalog = emoji_registry = None
    emoji_plan: list[PlannedEmoji] = []
    if run_emojis:
        emoji_catalog = load_emoji_catalog(args.emoji_catalog)
        emoji_registry = load_emoji_registry(args.emoji_registry)
        validate_emoji_asset_references(emoji_catalog)
        emoji_definitions = _filtered_emojis(emoji_catalog, key=args.key, prefix=args.prefix, strict=False)
        any_matches = any_matches or bool(emoji_definitions)
        if emoji_definitions:
            if args.dry_run:
                print("Emoji prepare: skipped for --dry-run")
            elif args.skip_prepare:
                print("Emoji prepare: skipped by --skip-prepare")
            else:
                prepare_emoji_assets(emoji_definitions)
            emoji_plan, emoji_summary = plan_emoji_definitions(emoji_definitions, emoji_registry)
            _print_emoji_plan(emoji_plan, emoji_summary)
            had_errors = had_errors or bool(emoji_summary.failed or emoji_summary.missing)
        else:
            print("Emoji assets: no matching keys")

    if not any_matches:
        raise SystemExit("No matching image or emoji assets.")
    if args.prepare_only:
        if had_errors:
            raise SystemExit(1)
        return
    if args.dry_run:
        if had_errors:
            raise SystemExit(1)
        return
    if had_errors:
        raise SystemExit("Asset validation failed; fix missing or invalid files before syncing.")

    settings = load_settings(require_token=True)
    if image_plan:
        if settings.discord_asset_channel_id is None:
            raise SystemExit("DISCORD_ASSET_CHANNEL_ID is required to synchronize Discord image assets.")
        asyncio.run(
            _sync_images_with_discord(
                token=settings.discord_bot_token,
                channel_id=settings.discord_asset_channel_id,
                planned=image_plan,
                registry=image_registry,
                registry_path=args.image_registry,
            )
        )
    if emoji_plan:
        if settings.discord_application_id is None:
            raise SystemExit("DISCORD_APPLICATION_ID is required to synchronize application emojis.")
        asyncio.run(
            _sync_emojis_with_discord(
                token=settings.discord_bot_token,
                application_id=settings.discord_application_id,
                planned=emoji_plan,
                registry=emoji_registry,
                registry_path=args.emoji_registry,
            )
        )


def prepare_image_assets(definitions: list[AssetDefinition], *, quality: int = 82) -> None:
    for definition in definitions:
        _prepare_image_asset(definition, quality=quality)


def prepare_emoji_assets(definitions: list[EmojiDefinition]) -> None:
    for definition in definitions:
        _prepare_emoji_asset(definition)


def plan_image_sync(
    catalog: AssetCatalog,
    registry: AssetRegistry,
    *,
    key: str | None = None,
    prefix: str | None = None,
) -> tuple[list[PlannedImageAsset], ImageSyncSummary]:
    if key and prefix:
        raise ValueError("Use --key or --prefix, not both.")
    return plan_image_definitions(_filtered_image_assets(catalog, key=key, prefix=prefix, strict=True), registry)


def plan_image_definitions(
    definitions: list[AssetDefinition],
    registry: AssetRegistry,
) -> tuple[list[PlannedImageAsset], ImageSyncSummary]:
    planned: list[PlannedImageAsset] = []
    summary = ImageSyncSummary()
    for definition in definitions:
        try:
            validation = validate_asset_file(definition)
        except Exception as exc:
            action = "missing" if not definition.path.exists() else "failed"
            if action == "missing":
                summary.missing += 1
            else:
                summary.failed += 1
            planned.append(PlannedImageAsset(definition=definition, image=None, action=action, error=str(exc)))
            continue

        existing = registry.get(definition.key)
        if existing and existing.sha256 == validation.image.sha256:
            summary.unchanged += 1
            planned.append(PlannedImageAsset(definition=definition, image=validation.image, action="unchanged"))
        elif existing:
            summary.updated += 1
            planned.append(PlannedImageAsset(definition=definition, image=validation.image, action="updated"))
        else:
            summary.uploaded += 1
            planned.append(PlannedImageAsset(definition=definition, image=validation.image, action="uploaded"))
    return planned, summary


async def sync_registry_with_channel(
    channel: Any,
    planned: list[PlannedImageAsset],
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


def plan_emoji_sync(
    catalog: EmojiCatalog,
    registry: EmojiRegistry,
    *,
    key: str | None = None,
    prefix: str | None = None,
) -> tuple[list[PlannedEmoji], EmojiSyncSummary]:
    if key and prefix:
        raise ValueError("Use --key or --prefix, not both.")
    return plan_emoji_definitions(_filtered_emojis(catalog, key=key, prefix=prefix, strict=True), registry)


def plan_emoji_definitions(
    definitions: list[EmojiDefinition],
    registry: EmojiRegistry,
) -> tuple[list[PlannedEmoji], EmojiSyncSummary]:
    planned: list[PlannedEmoji] = []
    summary = EmojiSyncSummary()
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


async def sync_emoji_registry_with_client(
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


def _prepare_image_asset(definition: AssetDefinition, *, quality: int) -> None:
    if definition.source_path is None:
        if not definition.path.exists():
            raise AssetValidationError(f"{definition.key} has no source_path and no prepared file")
        print(f"SKIP {definition.key}: no source_path; validating existing prepared file")
        return
    if definition.source_path.resolve() == definition.path.resolve():
        raise AssetValidationError(f"{definition.key} source_path must not be the prepared output path")
    if not definition.source_path.exists():
        raise AssetValidationError(f"{definition.key} source image is missing")

    spec = definition.spec
    if spec.width <= 0 or spec.height <= 0:
        raise AssetValidationError(f"{definition.key} does not have a fixed target size")
    before_info = inspect_image_file(definition.source_path)
    before = definition.source_path.stat().st_size
    definition.path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except Exception:
        _prepare_with_imagemagick(definition, quality=quality)
    else:
        try:
            with Image.open(definition.source_path) as image:
                image = ImageOps.exif_transpose(image)
                if image.width < spec.width or image.height < spec.height:
                    print(
                        f"WARN {definition.key}: source is {image.width}x{image.height}; "
                        f"target is {spec.width}x{spec.height}"
                    )
                resized = _resize_to_canvas(image, (spec.width, spec.height), spec_name=spec.name)
                resized.save(definition.path, **_save_kwargs(definition.path.suffix.lower(), quality=quality))
        except UnidentifiedImageError as error:
            raise AssetValidationError(f"{definition.key} source image is invalid") from error

    after_info = inspect_image_file(definition.path)
    savings = 100 - ((after_info.size_bytes / before) * 100) if before else 0
    print(
        f"PREP {definition.key}: {before_info.width}x{before_info.height} {before} bytes -> "
        f"{after_info.width}x{after_info.height} {after_info.size_bytes} bytes ({savings:.1f}% savings)"
    )


def _prepare_emoji_asset(definition: EmojiDefinition) -> None:
    if definition.source_path is None:
        if not definition.path.exists():
            raise AssetValidationError(f"{definition.key} has no source_path and no prepared file")
        print(f"SKIP {definition.key}: no source_path; validating existing prepared emoji")
        return
    if definition.source_path.resolve() == definition.path.resolve():
        raise AssetValidationError(f"{definition.key} source_path must not be the prepared output path")
    if not definition.source_path.exists():
        raise AssetValidationError(f"{definition.key} source image is missing")

    before_info = inspect_image_file(definition.source_path)
    before = definition.source_path.stat().st_size
    definition.path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except Exception:
        _prepare_emoji_with_imagemagick(definition)
        after_info = inspect_image_file(definition.path)
        savings = 100 - ((after_info.size_bytes / before) * 100) if before else 0
        print(
            f"PREP {definition.key}: {before_info.width}x{before_info.height} {before} bytes -> "
            f"{after_info.width}x{after_info.height} {after_info.size_bytes} bytes ({savings:.1f}% savings)"
        )
        return

    try:
        with Image.open(definition.source_path) as image:
            image = ImageOps.exif_transpose(image)
            resized = _resize_emoji(image, (128, 128))
            if definition.path.suffix.lower() in {".jpg", ".jpeg"} and resized.mode != "RGB":
                background = Image.new("RGB", resized.size, (10, 16, 30))
                background.paste(resized.convert("RGBA"), mask=resized.convert("RGBA").getchannel("A"))
                resized = background
            resized.save(definition.path, **_save_kwargs(definition.path.suffix.lower(), quality=92))
    except UnidentifiedImageError as error:
        raise AssetValidationError(f"{definition.key} source image is invalid") from error

    after_info = inspect_image_file(definition.path)
    savings = 100 - ((after_info.size_bytes / before) * 100) if before else 0
    print(
        f"PREP {definition.key}: {before_info.width}x{before_info.height} {before} bytes -> "
        f"{after_info.width}x{after_info.height} {after_info.size_bytes} bytes ({savings:.1f}% savings)"
    )


def _resize_to_canvas(image: Any, size: tuple[int, int], *, spec_name: str) -> Any:
    from PIL import Image, ImageOps

    background = (10, 16, 30)
    if spec_name == "thumbnail" and _has_alpha(image):
        image = image.convert("RGBA")
        scale = min(size[0] / image.width, size[1] / image.height)
        resized_size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        resized = image.resize(resized_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.alpha_composite(
            resized,
            ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2),
        )
        return canvas

    if _has_alpha(image):
        base = Image.new("RGBA", image.size, background + (255,))
        base.alpha_composite(image.convert("RGBA"))
        image = base
    mode = "RGBA" if spec_name == "thumbnail" and _has_alpha(image) else "RGB"
    if image.mode != mode:
        image = image.convert(mode)

    centering = (0.0, 0.5) if spec_name == "location_banner" else (0.5, 0.5)
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=centering)


def _resize_emoji(image: Any, size: tuple[int, int]) -> Any:
    from PIL import Image, ImageOps

    if _has_alpha(image):
        image = image.convert("RGBA")
        scale = min(size[0] / image.width, size[1] / image.height)
        resized_size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        resized = image.resize(resized_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.alpha_composite(
            resized,
            ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2),
        )
        return canvas
    if image.mode != "RGB":
        image = image.convert("RGB")
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _has_alpha(image: Any) -> bool:
    if image.mode in {"RGBA", "LA"}:
        return True
    return image.mode == "P" and "transparency" in image.info


def _prepare_with_imagemagick(definition: AssetDefinition, *, quality: int) -> None:
    convert = shutil.which("convert")
    if convert is None:
        raise SystemExit("Pillow is required to prepare images. Install project dependencies first.")
    spec = definition.spec
    if spec.name == "thumbnail":
        command = [
            convert,
            str(definition.source_path),
            "-auto-orient",
            "-resize",
            f"{spec.width}x{spec.height}",
            "-background",
            "none",
            "-gravity",
            "center",
            "-extent",
            f"{spec.width}x{spec.height}",
            "-quality",
            str(quality),
            str(definition.path),
        ]
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as error:
            raise AssetValidationError(f"{definition.key} could not be prepared with ImageMagick") from error
        return

    command = [
        convert,
        str(definition.source_path),
        "-auto-orient",
        "-resize",
        f"{spec.width}x{spec.height}^",
        "-background",
        "#0a101e",
        "-gravity",
        "west" if spec.name == "location_banner" else "center",
        "-extent",
        f"{spec.width}x{spec.height}",
        "-quality",
        str(quality),
        str(definition.path),
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise AssetValidationError(f"{definition.key} could not be prepared with ImageMagick") from error


def _prepare_emoji_with_imagemagick(definition: EmojiDefinition) -> None:
    convert = shutil.which("convert")
    if convert is None:
        raise SystemExit("Pillow or ImageMagick is required to prepare emojis. Install project dependencies first.")
    background = "none" if definition.path.suffix.lower() == ".png" else "#0a101e"
    command = [
        convert,
        str(definition.source_path),
        "-auto-orient",
        "-resize",
        "128x128",
        "-background",
        background,
        "-gravity",
        "center",
        "-extent",
        "128x128",
        str(definition.path),
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise AssetValidationError(f"{definition.key} could not be prepared with ImageMagick") from error


def _save_kwargs(suffix: str, *, quality: int) -> dict[str, object]:
    if suffix == ".webp":
        return {"format": "WEBP", "quality": quality, "method": 6}
    if suffix == ".png":
        return {"format": "PNG", "optimize": True}
    if suffix in {".jpg", ".jpeg"}:
        return {"format": "JPEG", "quality": quality, "optimize": True}
    raise AssetValidationError(f"Unsupported output extension: {suffix}")


def _filtered_image_assets(
    catalog: AssetCatalog,
    *,
    key: str | None,
    prefix: str | None,
    strict: bool,
) -> list[AssetDefinition]:
    if key:
        definition = catalog.assets.get(key)
        if definition is not None:
            return [definition]
        if strict:
            return [catalog.get(key)]
        return []
    if prefix:
        return [definition for asset_key, definition in sorted(catalog.assets.items()) if asset_key.startswith(prefix)]
    return [definition for _, definition in sorted(catalog.assets.items())]


def _filtered_emojis(
    catalog: EmojiCatalog,
    *,
    key: str | None,
    prefix: str | None,
    strict: bool,
) -> list[EmojiDefinition]:
    if key:
        definition = catalog.emojis.get(key)
        if definition is not None:
            return [definition]
        if strict:
            return [catalog.get(key)]
        return []
    if prefix:
        return [definition for emoji_key, definition in sorted(catalog.emojis.items()) if emoji_key.startswith(prefix)]
    return [definition for _, definition in sorted(catalog.emojis.items())]


def _print_image_plan(planned: list[PlannedImageAsset], summary: ImageSyncSummary) -> None:
    print("Image assets:")
    for item in planned:
        suffix = f" ({item.error})" if item.error else ""
        print(f"  {item.action.upper()} {item.definition.key}{suffix}")
    print(f"  Summary: {summary.as_dict()}")


def _print_emoji_plan(planned: list[PlannedEmoji], summary: EmojiSyncSummary) -> None:
    print("Emoji assets:")
    for item in planned:
        suffix = f" ({item.error})" if item.error else ""
        print(f"  {item.action.upper()} {item.definition.key} -> {item.definition.name}{suffix}")
    print(f"  Summary: {summary.as_dict()}")


async def _sync_images_with_discord(
    *,
    token: str,
    channel_id: int,
    planned: list[PlannedImageAsset],
    registry: AssetRegistry,
    registry_path: Path,
) -> None:
    client = _ImageSyncClient(channel_id=channel_id, planned=planned, registry=registry, registry_path=registry_path)
    try:
        await client.start(token)
    finally:
        if not client.is_closed():
            await client.close()


class _ImageSyncClient(discord.Client):
    def __init__(
        self,
        *,
        channel_id: int,
        planned: list[PlannedImageAsset],
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
            print(f"Image sync: uploaded_or_updated={uploaded_count} unchanged={unchanged_count}")
        finally:
            await self.close()


async def _sync_emojis_with_discord(
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
            updated_registry = await sync_emoji_registry_with_client(self, self.planned, self.registry)
            write_emoji_registry_atomic(updated_registry, self.registry_path)
            uploaded_count = sum(1 for item in self.planned if item.action in {"uploaded", "updated"})
            unchanged_count = sum(1 for item in self.planned if item.action == "unchanged")
            print(f"Emoji sync: uploaded_or_updated={uploaded_count} unchanged={unchanged_count}")
        finally:
            await self.close()


if __name__ == "__main__":
    main()
