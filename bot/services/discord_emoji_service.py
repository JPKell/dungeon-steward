from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.services.discord_asset_service import ASSET_ROOT, CONTENT_DIR, PROJECT_ROOT, AssetConfigError, inspect_image_file

DEFAULT_EMOJI_CATALOG_PATH = CONTENT_DIR / "emoji_assets.json"
DEFAULT_EMOJI_REGISTRY_PATH = CONTENT_DIR / "emoji_asset_registry.json"

_EMOJI_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{2,32}$")
_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*(?:\.[a-z0-9]+)?$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class EmojiDefinition:
    key: str
    name: str
    path: Path
    alt_text: str
    required: bool = False
    source_path: Path | None = None

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class EmojiRegistryEntry:
    key: str
    name: str
    emoji_id: str
    sha256: str
    animated: bool
    uploaded_at: str

    @property
    def markdown(self) -> str:
        prefix = "a" if self.animated else ""
        return f"<{prefix}:{self.name}:{self.emoji_id}>"


@dataclass(frozen=True)
class EmojiCatalog:
    version: int
    emojis: dict[str, EmojiDefinition]

    def get(self, key: str) -> EmojiDefinition:
        try:
            return self.emojis[key]
        except KeyError as error:
            raise AssetConfigError(f"Unknown Discord emoji asset key: {key}") from error


@dataclass(frozen=True)
class EmojiRegistry:
    version: int
    emojis: dict[str, EmojiRegistryEntry]

    def get(self, key: str | None) -> EmojiRegistryEntry | None:
        if not key:
            return None
        return self.emojis.get(key)


class DiscordEmojiService:
    """Resolves logical asset keys to custom/application emoji markdown."""

    def __init__(
        self,
        *,
        catalog: EmojiCatalog | None = None,
        registry: EmojiRegistry | None = None,
        catalog_path: Path | None = None,
        registry_path: Path | None = None,
    ) -> None:
        self.catalog = catalog or load_emoji_catalog(catalog_path)
        self.registry = registry or load_emoji_registry(registry_path)

    def markdown_for(self, asset_key: str | None) -> str | None:
        entry = self.registry.get(asset_key)
        return entry.markdown if entry is not None else None

    def registry_entry_for(self, asset_key: str | None) -> EmojiRegistryEntry | None:
        return self.registry.get(asset_key)


def referenced_emoji_asset_keys(content_dir: Path = CONTENT_DIR) -> set[str]:
    keys: set[str] = set()
    for path in content_dir.glob("*.json"):
        if path.name in {"emoji_assets.json", "emoji_asset_registry.json", "image_assets.json", "image_asset_registry.json"}:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _collect_emoji_keys(raw, keys, content_file=path.name)
    return keys


def validate_emoji_asset_references(catalog: EmojiCatalog, content_dir: Path = CONTENT_DIR) -> None:
    missing = sorted(referenced_emoji_asset_keys(content_dir) - set(catalog.emojis))
    if missing:
        raise AssetConfigError(f"Potion content references unknown emoji assets: {', '.join(missing)}")


def load_emoji_catalog(
    path: Path | None = None,
    *,
    asset_root: Path = ASSET_ROOT,
    validate_files: bool = False,
    document: dict[str, Any] | None = None,
) -> EmojiCatalog:
    catalog_path = path or DEFAULT_EMOJI_CATALOG_PATH
    if document is None and not catalog_path.exists():
        return EmojiCatalog(version=1, emojis={})
    raw = document if document is not None else _load_json_object(catalog_path)
    version = raw.get("version")
    if version != 1:
        raise AssetConfigError("emoji_assets.json version must be 1")
    emojis_raw = raw.get("emojis")
    if not isinstance(emojis_raw, dict):
        raise AssetConfigError("emoji_assets.json must contain an emojis object")

    emojis: dict[str, EmojiDefinition] = {}
    for key, entry in emojis_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise AssetConfigError("Emoji asset keys must be non-empty strings")
        if not isinstance(entry, dict):
            raise AssetConfigError(f"Emoji asset {key} must be an object")
        definition = _emoji_definition(key.strip(), entry, catalog_path=catalog_path, asset_root=asset_root)
        if validate_files:
            validate_emoji_file(definition)
        emojis[definition.key] = definition
    return EmojiCatalog(version=version, emojis=emojis)


def load_emoji_registry(path: Path | None = None, *, document: dict[str, Any] | None = None) -> EmojiRegistry:
    registry_path = path or DEFAULT_EMOJI_REGISTRY_PATH
    if document is None and not registry_path.exists():
        return EmojiRegistry(version=1, emojis={})
    raw = document if document is not None else _load_json_object(registry_path)
    version = raw.get("version")
    if version != 1:
        raise AssetConfigError("emoji_asset_registry.json version must be 1")
    emojis_raw = raw.get("emojis")
    if not isinstance(emojis_raw, dict):
        raise AssetConfigError("emoji_asset_registry.json must contain an emojis object")

    emojis: dict[str, EmojiRegistryEntry] = {}
    for key, entry in emojis_raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise AssetConfigError("Emoji registry entries must be keyed objects")
        emojis[key] = _emoji_registry_entry(key, entry)
    return EmojiRegistry(version=version, emojis=emojis)


def write_emoji_registry_atomic(registry: EmojiRegistry, path: Path | None = None, *, backup: bool = True) -> None:
    registry_path = path or DEFAULT_EMOJI_REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = emoji_registry_to_json(registry)
    if backup and registry_path.exists():
        shutil.copy2(registry_path, registry_path.with_suffix(registry_path.suffix + ".bak"))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=registry_path.parent, delete=False) as handle:
        tmp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, registry_path)


def emoji_registry_to_json(registry: EmojiRegistry) -> dict[str, Any]:
    return {
        "version": registry.version,
        "emojis": {
            key: {
                "name": entry.name,
                "emoji_id": entry.emoji_id,
                "sha256": entry.sha256,
                "animated": entry.animated,
                "uploaded_at": entry.uploaded_at,
            }
            for key, entry in sorted(registry.emojis.items())
        },
    }


def validate_emoji_file(definition: EmojiDefinition) -> None:
    if not definition.path.exists():
        raise AssetConfigError(f"{definition.key} references missing emoji file {definition.path.name}")
    image = inspect_image_file(definition.path)
    if image.format not in {"png", "jpeg"}:
        raise AssetConfigError(f"{definition.key} emoji image must be PNG or JPEG")
    if image.width != 128 or image.height != 128:
        raise AssetConfigError(f"{definition.key} emoji image must be 128x128, found {image.width}x{image.height}")
    if image.size_bytes > 256 * 1024:
        raise AssetConfigError(f"{definition.key} emoji image is too large: {image.size_bytes} bytes")


def validate_emoji_registry_integrity(
    catalog: EmojiCatalog,
    registry: EmojiRegistry,
    *,
    require_required_emojis: bool = False,
    require_current_files: bool = True,
) -> None:
    unknown_registry_keys = sorted(set(registry.emojis) - set(catalog.emojis))
    if unknown_registry_keys:
        raise AssetConfigError(f"Emoji registry contains unknown keys: {', '.join(unknown_registry_keys)}")
    missing_required = [
        key
        for key, definition in sorted(catalog.emojis.items())
        if definition.required and registry.get(key) is None
    ]
    if require_required_emojis and missing_required:
        raise AssetConfigError(f"Required emoji assets are not registered: {', '.join(missing_required)}")
    for key, entry in registry.emojis.items():
        definition = catalog.get(key)
        if entry.name != definition.name:
            raise AssetConfigError(f"{key} emoji registry name does not match catalog name")
        if require_current_files and definition.path.exists() and entry.sha256 != sha256_file(definition.path):
            raise AssetConfigError(f"{key} emoji registry SHA-256 does not match local file")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def emoji_entry_from_upload(
    *,
    key: str,
    definition: EmojiDefinition,
    emoji_id: int | str,
    sha256: str,
    animated: bool = False,
    uploaded_at: datetime | None = None,
) -> EmojiRegistryEntry:
    uploaded_at = uploaded_at or datetime.now(UTC)
    return EmojiRegistryEntry(
        key=key,
        name=definition.name,
        emoji_id=str(emoji_id),
        sha256=sha256.lower(),
        animated=animated,
        uploaded_at=uploaded_at.isoformat(),
    )


def _emoji_definition(key: str, entry: dict[str, Any], *, catalog_path: Path, asset_root: Path) -> EmojiDefinition:
    name = _required_str(entry, "name", key)
    if not _EMOJI_NAME_RE.match(name):
        raise AssetConfigError(f"{key} emoji name must be 2-32 letters, numbers, or underscores")
    path = _asset_path(
        _required_str(entry, "path", key),
        catalog_path=catalog_path,
        asset_root=asset_root,
        key=key,
        allowed_suffixes={".png", ".jpg", ".jpeg"},
        label="emoji image",
    )
    alt_text = _optional_str(entry, "alt_text", key) or name.replace("_", " ")
    required = entry.get("required", False)
    if not isinstance(required, bool):
        raise AssetConfigError(f"{key} required must be boolean")
    source_raw = entry.get("source_path")
    source_path = None
    if source_raw is not None:
        source_path = _asset_path(
            _required_str(entry, "source_path", key),
            catalog_path=catalog_path,
            asset_root=asset_root,
            key=key,
            allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
            label="emoji source image",
        )
    return EmojiDefinition(key=key, name=name, path=path, alt_text=alt_text, required=required, source_path=source_path)


def _asset_path(
    raw_path: str,
    *,
    catalog_path: Path,
    asset_root: Path,
    key: str,
    allowed_suffixes: set[str],
    label: str,
) -> Path:
    value = Path(raw_path)
    if value.is_absolute():
        raise AssetConfigError(f"{key} path must be relative")
    root = asset_root.resolve()
    base = catalog_path.parents[2].resolve() if len(catalog_path.parents) >= 3 else PROJECT_ROOT
    resolved = (base / value).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AssetConfigError(f"{key} path must stay inside {asset_root}") from error
    if not _FILENAME_RE.match(resolved.name):
        raise AssetConfigError(f"{key} filename must use lowercase snake_case")
    if resolved.suffix.lower() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise AssetConfigError(f"{key} {label} must use one of: {allowed}")
    return resolved


def _emoji_registry_entry(key: str, entry: dict[str, Any]) -> EmojiRegistryEntry:
    name = _required_str(entry, "name", key)
    if not _EMOJI_NAME_RE.match(name):
        raise AssetConfigError(f"{key} registry emoji name is invalid")
    emoji_id = _required_str(entry, "emoji_id", key)
    if not emoji_id.isdigit():
        raise AssetConfigError(f"{key} registry emoji_id must be numeric")
    sha256 = _required_str(entry, "sha256", key)
    if not _SHA256_RE.match(sha256):
        raise AssetConfigError(f"{key} registry SHA-256 is invalid")
    animated = entry.get("animated", False)
    if not isinstance(animated, bool):
        raise AssetConfigError(f"{key} registry animated must be boolean")
    return EmojiRegistryEntry(
        key=key,
        name=name,
        emoji_id=emoji_id,
        sha256=sha256.lower(),
        animated=animated,
        uploaded_at=_required_str(entry, "uploaded_at", key),
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise AssetConfigError(f"{path.name} is invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise AssetConfigError(f"{path.name} must be a JSON object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AssetConfigError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _collect_emoji_keys(value: Any, keys: set[str], *, content_file: str) -> None:
    if isinstance(value, dict):
        for field, item in value.items():
            is_legacy_potion_emoji = content_file == "potion_items.json" and field == "thumbnail_asset"
            if (field == "emoji_asset" or is_legacy_potion_emoji) and isinstance(item, str) and item.strip():
                keys.add(item.strip())
            else:
                _collect_emoji_keys(item, keys, content_file=content_file)
    elif isinstance(value, list):
        for item in value:
            _collect_emoji_keys(item, keys, content_file=content_file)


def _required_str(entry: dict[str, Any], field: str, key: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AssetConfigError(f"{key} missing string field: {field}")
    return value.strip()


def _optional_str(entry: dict[str, Any], field: str, key: str) -> str | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AssetConfigError(f"{key} {field} must be a non-empty string when provided")
    return value.strip()


DEFAULT_DISCORD_EMOJIS = DiscordEmojiService()


def refresh_default_discord_emojis(
    *,
    catalog_document: dict[str, Any],
    registry_document: dict[str, Any],
) -> DiscordEmojiService:
    global DEFAULT_DISCORD_EMOJIS
    DEFAULT_DISCORD_EMOJIS = DiscordEmojiService(
        catalog=load_emoji_catalog(document=catalog_document),
        registry=load_emoji_registry(document=registry_document),
    )
    return DEFAULT_DISCORD_EMOJIS
