from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTENT_DIR = PROJECT_ROOT / "bot" / "content"
ASSET_ROOT = PROJECT_ROOT / "assets" / "discord"
DEFAULT_CATALOG_PATH = CONTENT_DIR / "image_assets.json"
DEFAULT_REGISTRY_PATH = CONTENT_DIR / "image_asset_registry.json"

DISCORD_ATTACHMENT_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})
GAMEPLAY_ASSET_FIELDS = frozenset({"thumbnail_asset", "banner_asset", "artwork_asset", "image_asset"})
_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*(?:\.[a-z0-9]+)?$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class AssetConfigError(ValueError):
    """Raised when image asset configuration is invalid."""


class UnknownAssetError(AssetConfigError):
    """Raised when code asks for an asset key that is not in the catalog."""


class MissingRequiredAssetError(AssetConfigError):
    """Raised when a required asset cannot be resolved from the registry or fallback."""


class AssetValidationError(AssetConfigError):
    """Raised when a local image file does not meet the asset standards."""


@dataclass(frozen=True)
class AssetTypeSpec:
    name: str
    width: int
    height: int
    preferred_format: str
    allowed_formats: frozenset[str]
    warning_max_bytes: int
    hard_max_bytes: int
    target_size_label: str


ASSET_TYPE_SPECS: dict[str, AssetTypeSpec] = {
    "thumbnail": AssetTypeSpec(
        name="thumbnail",
        width=256,
        height=256,
        preferred_format="webp",
        allowed_formats=frozenset({"webp", "png"}),
        warning_max_bytes=150 * 1024,
        hard_max_bytes=250 * 1024,
        target_size_label="40-100 KB",
    ),
    "location_banner": AssetTypeSpec(
        name="location_banner",
        width=1200,
        height=400,
        preferred_format="webp",
        allowed_formats=frozenset({"webp", "png", "jpeg"}),
        warning_max_bytes=500 * 1024,
        hard_max_bytes=750 * 1024,
        target_size_label="200-350 KB",
    ),
    "encounter_artwork": AssetTypeSpec(
        name="encounter_artwork",
        width=1200,
        height=675,
        preferred_format="webp",
        allowed_formats=frozenset({"webp", "png", "jpeg"}),
        warning_max_bytes=750 * 1024,
        hard_max_bytes=1024 * 1024,
        target_size_label="300-600 KB",
    ),
}

EXTENSION_FORMATS = {
    ".png": "png",
    ".webp": "webp",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
}


@dataclass(frozen=True)
class ImageInfo:
    path: Path
    format: str
    width: int
    height: int
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class AssetDefinition:
    key: str
    type: str
    path: Path
    alt_text: str
    required: bool
    source_path: Path | None = None

    @property
    def spec(self) -> AssetTypeSpec:
        return ASSET_TYPE_SPECS[self.type]

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class RegistryAsset:
    key: str
    type: str
    filename: str
    sha256: str
    width: int
    height: int
    size_bytes: int
    channel_id: str
    message_id: str
    attachment_id: str
    cdn_url: str
    uploaded_at: str


@dataclass(frozen=True)
class AssetCatalog:
    version: int
    assets: dict[str, AssetDefinition]

    def get(self, key: str) -> AssetDefinition:
        try:
            return self.assets[key]
        except KeyError as error:
            raise UnknownAssetError(f"Unknown image asset key: {key}") from error


@dataclass(frozen=True)
class AssetRegistry:
    version: int
    assets: dict[str, RegistryAsset]

    def get(self, key: str) -> RegistryAsset | None:
        return self.assets.get(key)


@dataclass(frozen=True)
class AssetValidationResult:
    definition: AssetDefinition
    image: ImageInfo
    warnings: tuple[str, ...]


def load_catalog(
    path: Path | None = None,
    *,
    asset_root: Path = ASSET_ROOT,
    validate_files: bool = False,
    document: dict[str, Any] | None = None,
) -> AssetCatalog:
    catalog_path = path or DEFAULT_CATALOG_PATH
    raw = document if document is not None else _load_json_object(catalog_path)
    version = raw.get("version")
    if version != 1:
        raise AssetConfigError("image_assets.json version must be 1")
    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, dict):
        raise AssetConfigError("image_assets.json must contain an assets object")

    assets: dict[str, AssetDefinition] = {}
    for key, entry in assets_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise AssetConfigError("Image asset keys must be non-empty strings")
        if not isinstance(entry, dict):
            raise AssetConfigError(f"Image asset {key} must be an object")
        definition = _asset_definition(key.strip(), entry, catalog_path=catalog_path, asset_root=asset_root)
        if validate_files:
            validate_asset_file(definition)
        assets[definition.key] = definition
    return AssetCatalog(version=version, assets=assets)


def load_registry(path: Path | None = None, *, document: dict[str, Any] | None = None) -> AssetRegistry:
    registry_path = path or DEFAULT_REGISTRY_PATH
    if document is None and not registry_path.exists():
        return AssetRegistry(version=1, assets={})
    raw = document if document is not None else _load_json_object(registry_path)
    version = raw.get("version")
    if version != 1:
        raise AssetConfigError("image_asset_registry.json version must be 1")
    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, dict):
        raise AssetConfigError("image_asset_registry.json must contain an assets object")

    assets: dict[str, RegistryAsset] = {}
    for key, entry in assets_raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise AssetConfigError("Registry asset entries must be keyed objects")
        assets[key] = _registry_asset(key, entry)
    return AssetRegistry(version=version, assets=assets)


def write_registry_atomic(registry: AssetRegistry, path: Path | None = None, *, backup: bool = True) -> None:
    registry_path = path or DEFAULT_REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = registry_to_json(registry)
    if backup and registry_path.exists():
        shutil.copy2(registry_path, registry_path.with_suffix(registry_path.suffix + ".bak"))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=registry_path.parent, delete=False) as handle:
        tmp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, registry_path)


def registry_to_json(registry: AssetRegistry) -> dict[str, Any]:
    return {
        "version": registry.version,
        "assets": {
            key: {
                "type": asset.type,
                "filename": asset.filename,
                "sha256": asset.sha256,
                "width": asset.width,
                "height": asset.height,
                "size_bytes": asset.size_bytes,
                "channel_id": asset.channel_id,
                "message_id": asset.message_id,
                "attachment_id": asset.attachment_id,
                "cdn_url": asset.cdn_url,
                "uploaded_at": asset.uploaded_at,
            }
            for key, asset in sorted(registry.assets.items())
        },
    }


def validate_asset_file(definition: AssetDefinition) -> AssetValidationResult:
    if not definition.path.exists():
        raise AssetValidationError(f"{definition.key} references missing file {definition.path.name}")
    image = inspect_image_file(definition.path)
    spec = definition.spec
    warnings: list[str] = []

    expected_format = EXTENSION_FORMATS.get(definition.path.suffix.lower())
    if expected_format is None:
        raise AssetValidationError(f"{definition.key} uses unsupported extension {definition.path.suffix}")
    if image.format != expected_format:
        raise AssetValidationError(f"{definition.key} extension does not match actual image format")
    if image.format not in spec.allowed_formats:
        raise AssetValidationError(f"{definition.key} must use one of {sorted(spec.allowed_formats)}")
    if image.width != spec.width or image.height != spec.height:
        raise AssetValidationError(f"{definition.key} must be {spec.width}x{spec.height}, found {image.width}x{image.height}")
    if image.size_bytes > spec.hard_max_bytes:
        raise AssetValidationError(f"{definition.key} is too large: {image.size_bytes} bytes")
    if image.size_bytes > spec.warning_max_bytes:
        warnings.append(f"{definition.key} exceeds warning threshold: {image.size_bytes} bytes")
    if image.format != spec.preferred_format:
        warnings.append(f"{definition.key} uses {image.format}; preferred format is {spec.preferred_format}")
    return AssetValidationResult(definition=definition, image=image, warnings=tuple(warnings))


def inspect_image_file(path: Path) -> ImageInfo:
    data = path.read_bytes()
    if not data:
        raise AssetValidationError(f"{path.name} is empty")
    image_format, width, height = _image_dimensions(data, path.name)
    return ImageInfo(
        path=path,
        format=image_format,
        width=width,
        height=height,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_discord_attachment_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in DISCORD_ATTACHMENT_HOSTS or not parsed.path.startswith("/attachments/"):
        raise AssetValidationError("Only Discord attachment CDN URLs can be normalized")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def registry_asset_from_upload(
    *,
    key: str,
    definition: AssetDefinition,
    image: ImageInfo,
    channel_id: int | str,
    message_id: int | str,
    attachment_id: int | str,
    cdn_url: str,
    uploaded_at: datetime | None = None,
) -> RegistryAsset:
    uploaded_at = uploaded_at or datetime.now(UTC)
    return RegistryAsset(
        key=key,
        type=definition.type,
        filename=definition.filename,
        sha256=image.sha256,
        width=image.width,
        height=image.height,
        size_bytes=image.size_bytes,
        channel_id=str(channel_id),
        message_id=str(message_id),
        attachment_id=str(attachment_id),
        cdn_url=normalize_discord_attachment_url(cdn_url),
        uploaded_at=uploaded_at.isoformat(),
    )


def referenced_gameplay_asset_keys(content_dir: Path = CONTENT_DIR) -> set[str]:
    keys: set[str] = set()
    for path in content_dir.glob("*.json"):
        if path.name in {"image_assets.json", "image_asset_registry.json", "content_validation.json", "simulation_results.json"}:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _collect_asset_keys(raw, keys)
    return keys


def validate_gameplay_asset_references(catalog: AssetCatalog, content_dir: Path = CONTENT_DIR) -> None:
    missing = sorted(referenced_gameplay_asset_keys(content_dir) - set(catalog.assets))
    if missing:
        raise AssetConfigError(f"Gameplay content references unknown image assets: {', '.join(missing)}")


def validate_registry_integrity(
    catalog: AssetCatalog,
    registry: AssetRegistry,
    *,
    require_required_assets: bool = False,
) -> None:
    unknown_registry_keys = sorted(set(registry.assets) - set(catalog.assets))
    if unknown_registry_keys:
        raise AssetConfigError(f"Registry contains unknown image asset keys: {', '.join(unknown_registry_keys)}")
    missing_required = [
        key
        for key, definition in sorted(catalog.assets.items())
        if definition.required and registry.get(key) is None
    ]
    if require_required_assets and missing_required:
        raise MissingRequiredAssetError(f"Required image assets are not registered: {', '.join(missing_required)}")
    for key, entry in registry.assets.items():
        definition = catalog.get(key)
        if entry.type != definition.type:
            raise AssetConfigError(f"{key} registry type does not match catalog type")
        if definition.path.exists():
            image = inspect_image_file(definition.path)
            if entry.sha256 != image.sha256:
                raise AssetConfigError(f"{key} registry SHA-256 does not match local file")
            if entry.width != image.width or entry.height != image.height:
                raise AssetConfigError(f"{key} registry dimensions do not match local file")
            if entry.size_bytes != image.size_bytes:
                raise AssetConfigError(f"{key} registry file size does not match local file")


class DiscordAssetService:
    """Resolves logical image asset keys to cached Discord CDN URLs for embeds."""

    def __init__(
        self,
        *,
        catalog: AssetCatalog | None = None,
        registry: AssetRegistry | None = None,
        catalog_path: Path | None = None,
        registry_path: Path | None = None,
        environment: str | None = None,
        allow_local_fallback: bool | None = None,
    ) -> None:
        self.catalog = catalog or load_catalog(catalog_path)
        self.registry = registry or load_registry(registry_path)
        self.environment = (environment or _configured_environment()).lower()
        self.allow_local_fallback = self.environment == "development" if allow_local_fallback is None else allow_local_fallback
        self._logged_fallback_keys: set[str] = set()

    def has_asset(self, asset_key: str) -> bool:
        return asset_key in self.catalog.assets and self.registry.get(asset_key) is not None

    def get_url(self, asset_key: str | None) -> str | None:
        if not asset_key:
            return None
        try:
            definition = self.catalog.get(asset_key)
        except UnknownAssetError:
            log.warning("Unknown Discord image asset key: %s", asset_key)
            return None
        entry = self.registry.get(asset_key)
        if entry is not None:
            return entry.cdn_url
        if self.allow_local_fallback and definition.path.exists():
            if asset_key not in self._logged_fallback_keys:
                log.info("Using local Discord image fallback for asset key %s", asset_key)
                self._logged_fallback_keys.add(asset_key)
            return f"attachment://{definition.filename}"
        if definition.required:
            raise MissingRequiredAssetError(f"Required Discord image asset is not registered: {asset_key}")
        log.info("Optional Discord image asset is not registered: %s", asset_key)
        return None

    def require_url(self, asset_key: str) -> str:
        definition = self.catalog.get(asset_key)
        url = self.get_url(definition.key)
        if url is None:
            raise MissingRequiredAssetError(f"Discord image asset is not registered: {asset_key}")
        return url

    def apply_thumbnail(self, embed: Any, asset_key: str | None) -> None:
        self._apply(embed, asset_key, expected_types={"thumbnail"}, method_name="set_thumbnail")

    def apply_banner(self, embed: Any, asset_key: str | None) -> None:
        self._apply(embed, asset_key, expected_types={"location_banner", "encounter_artwork"}, method_name="set_image")

    def _apply(self, embed: Any, asset_key: str | None, *, expected_types: set[str], method_name: str) -> None:
        if not asset_key:
            return
        definition = self.catalog.get(asset_key)
        if definition.type not in expected_types:
            raise AssetConfigError(f"{asset_key} is {definition.type}, not one of {sorted(expected_types)}")
        url = self.get_url(asset_key)
        if url:
            getattr(embed, method_name)(url=url)


def _asset_definition(key: str, entry: dict[str, Any], *, catalog_path: Path, asset_root: Path) -> AssetDefinition:
    asset_type = _required_str(entry, "type", key)
    if asset_type not in ASSET_TYPE_SPECS:
        raise AssetConfigError(f"{key} has unsupported asset type: {asset_type}")
    path = _asset_path(_required_str(entry, "path", key), catalog_path=catalog_path, asset_root=asset_root, key=key)
    alt_text = _required_str(entry, "alt_text", key)
    required = entry.get("required", False)
    if not isinstance(required, bool):
        raise AssetConfigError(f"{key} required must be boolean")
    source_raw = entry.get("source_path")
    source_path = None
    if source_raw is not None:
        if not isinstance(source_raw, str) or not source_raw.strip():
            raise AssetConfigError(f"{key} source_path must be a string")
        source_path = _asset_path(source_raw, catalog_path=catalog_path, asset_root=asset_root, key=key)
    return AssetDefinition(key=key, type=asset_type, path=path, alt_text=alt_text, required=required, source_path=source_path)


def _asset_path(raw_path: str, *, catalog_path: Path, asset_root: Path, key: str) -> Path:
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
    if resolved.suffix.lower() not in EXTENSION_FORMATS:
        raise AssetConfigError(f"{key} uses unsupported image extension {resolved.suffix}")
    return resolved


def _registry_asset(key: str, entry: dict[str, Any]) -> RegistryAsset:
    asset_type = _required_str(entry, "type", key)
    if asset_type not in ASSET_TYPE_SPECS:
        raise AssetConfigError(f"{key} has unsupported registry asset type: {asset_type}")
    filename = _required_str(entry, "filename", key)
    if not _FILENAME_RE.match(filename):
        raise AssetConfigError(f"{key} registry filename must use lowercase snake_case")
    sha256 = _required_str(entry, "sha256", key)
    if not _SHA256_RE.match(sha256):
        raise AssetConfigError(f"{key} registry SHA-256 is invalid")
    cdn_url = normalize_discord_attachment_url(_required_str(entry, "cdn_url", key))
    return RegistryAsset(
        key=key,
        type=asset_type,
        filename=filename,
        sha256=sha256.lower(),
        width=_required_int(entry, "width", key),
        height=_required_int(entry, "height", key),
        size_bytes=_required_int(entry, "size_bytes", key),
        channel_id=_required_str(entry, "channel_id", key),
        message_id=_required_str(entry, "message_id", key),
        attachment_id=_required_str(entry, "attachment_id", key),
        cdn_url=cdn_url,
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


def _required_str(entry: dict[str, Any], field: str, key: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AssetConfigError(f"{key} missing string field: {field}")
    return value.strip()


def _required_int(entry: dict[str, Any], field: str, key: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise AssetConfigError(f"{key} missing integer field: {field}")
    return value


def _image_dimensions(data: bytes, filename: str) -> tuple[str, int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise AssetValidationError(f"{filename} has invalid PNG header")
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data, filename)
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_dimensions(data, filename)
    raise AssetValidationError(f"{filename} is not a supported image format")


def _jpeg_dimensions(data: bytes, filename: str) -> tuple[str, int, int]:
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2:
            break
        if 0xC0 <= marker <= 0xC3 and offset + 7 < len(data):
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return "jpeg", width, height
        offset += segment_length
    raise AssetValidationError(f"{filename} has invalid JPEG dimensions")


def _webp_dimensions(data: bytes, filename: str) -> tuple[str, int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return "webp", width, height
    if chunk == b"VP8L":
        if len(data) < 25 or data[20] != 0x2F:
            raise AssetValidationError(f"{filename} has invalid WebP lossless header")
        b0, b1, b2, b3 = data[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return "webp", width, height
    if chunk == b"VP8 ":
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            raise AssetValidationError(f"{filename} has invalid WebP lossy header")
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return "webp", width, height
    raise AssetValidationError(f"{filename} has unsupported WebP chunk")


def _collect_asset_keys(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in GAMEPLAY_ASSET_FIELDS and isinstance(item, str) and item.strip():
                keys.add(item.strip())
            else:
                _collect_asset_keys(item, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_asset_keys(item, keys)


def _configured_environment() -> str:
    try:
        from bot.config import load_settings

        return load_settings(require_token=False).environment
    except Exception:
        return os.getenv("ENVIRONMENT", "development")


DEFAULT_DISCORD_ASSETS = DiscordAssetService()


def refresh_default_discord_assets(
    *,
    catalog_document: dict[str, Any],
    registry_document: dict[str, Any],
) -> DiscordAssetService:
    global DEFAULT_DISCORD_ASSETS
    DEFAULT_DISCORD_ASSETS = DiscordAssetService(
        catalog=load_catalog(document=catalog_document),
        registry=load_registry(document=registry_document),
    )
    return DEFAULT_DISCORD_ASSETS
