from __future__ import annotations

import json
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path

import discord
import pytest

from bot.services.discord_asset_service import (
    AssetRegistry,
    AssetValidationError,
    DiscordAssetService,
    MissingRequiredAssetError,
    RegistryAsset,
    inspect_image_file,
    load_catalog,
    load_registry,
    normalize_discord_attachment_url,
    registry_asset_from_upload,
    validate_asset_file,
    validate_gameplay_asset_references,
    write_registry_atomic,
)
from scripts.sync_discord_assets import plan_sync, sync_registry_with_channel


def test_catalog_loading_and_asset_file_validation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    image_path = _write_png(project / "assets/discord/thumbnails/items/test_item.png", 256, 256)
    catalog_path = _write_catalog(
        project,
        {
            "item.test": {
                "type": "thumbnail",
                "path": "assets/discord/thumbnails/items/test_item.png",
                "alt_text": "A test item",
                "required": False,
            }
        },
    )

    catalog = load_catalog(catalog_path, asset_root=project / "assets/discord", validate_files=True)
    result = validate_asset_file(catalog.get("item.test"))
    info = inspect_image_file(image_path)

    assert catalog.get("item.test").alt_text == "A test item"
    assert result.image.width == 256
    assert info.sha256 == result.image.sha256


def test_registry_loading_normalizes_discord_urls(tmp_path: Path) -> None:
    registry_path = tmp_path / "image_asset_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": {
                    "location.test": {
                        "type": "location_banner",
                        "filename": "test.png",
                        "sha256": "a" * 64,
                        "width": 1200,
                        "height": 400,
                        "size_bytes": 123,
                        "channel_id": "1",
                        "message_id": "2",
                        "attachment_id": "3",
                        "cdn_url": "https://cdn.discordapp.com/attachments/1/3/test.png?ex=signed#frag",
                        "uploaded_at": "2026-07-04T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    registry = load_registry(registry_path)

    assert registry.get("location.test").cdn_url == "https://cdn.discordapp.com/attachments/1/3/test.png"


def test_unknown_optional_and_required_asset_handling(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_png(project / "assets/discord/thumbnails/items/optional_item.png", 256, 256)
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "item.optional": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/optional_item.png",
                    "alt_text": "Optional",
                    "required": False,
                },
                "item.required": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/optional_item.png",
                    "alt_text": "Required",
                    "required": True,
                },
            },
        ),
        asset_root=project / "assets/discord",
    )
    service = DiscordAssetService(catalog=catalog, registry=AssetRegistry(version=1, assets={}), allow_local_fallback=False)

    assert service.get_url("item.unknown") is None
    assert service.get_url("item.optional") is None
    with pytest.raises(MissingRequiredAssetError):
        service.get_url("item.required")


def test_url_normalizer_rejects_unrelated_urls() -> None:
    assert (
        normalize_discord_attachment_url("https://media.discordapp.net/attachments/1/2/test.webp?ex=secret")
        == "https://media.discordapp.net/attachments/1/2/test.webp"
    )
    with pytest.raises(AssetValidationError):
        normalize_discord_attachment_url("https://example.com/attachments/1/2/test.webp?ex=secret")


def test_dimension_and_file_size_validation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_png(project / "assets/discord/thumbnails/items/wrong_size.png", 128, 128)
    large = _write_png(project / "assets/discord/thumbnails/items/too_large.png", 256, 256)
    with large.open("ab") as handle:
        handle.write(b"x" * (260 * 1024))
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "item.wrong": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/wrong_size.png",
                    "alt_text": "Wrong",
                    "required": False,
                },
                "item.large": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/too_large.png",
                    "alt_text": "Large",
                    "required": False,
                },
            },
        ),
        asset_root=project / "assets/discord",
    )

    with pytest.raises(AssetValidationError, match="must be 256x256"):
        validate_asset_file(catalog.get("item.wrong"))
    with pytest.raises(AssetValidationError, match="too large"):
        validate_asset_file(catalog.get("item.large"))


def test_plan_sync_skips_unchanged_assets(tmp_path: Path) -> None:
    project = _project(tmp_path)
    image_path = _write_png(project / "assets/discord/thumbnails/items/test_item.png", 256, 256)
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "item.test": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/test_item.png",
                    "alt_text": "A test item",
                    "required": False,
                }
            },
        ),
        asset_root=project / "assets/discord",
    )
    image = inspect_image_file(image_path)
    registry = AssetRegistry(
        version=1,
        assets={
            "item.test": RegistryAsset(
                key="item.test",
                type="thumbnail",
                filename="test_item.png",
                sha256=image.sha256,
                width=256,
                height=256,
                size_bytes=image.size_bytes,
                channel_id="1",
                message_id="2",
                attachment_id="3",
                cdn_url="https://cdn.discordapp.com/attachments/1/3/test_item.png",
                uploaded_at="2026-07-04T00:00:00+00:00",
            )
        },
    )

    planned, summary = plan_sync(catalog, registry)

    assert planned[0].action == "unchanged"
    assert summary.as_dict()["unchanged"] == 1


def test_atomic_registry_write_creates_backup(tmp_path: Path) -> None:
    registry_path = tmp_path / "image_asset_registry.json"
    registry_path.write_text('{"version":1,"assets":{}}\n', encoding="utf-8")
    registry = AssetRegistry(
        version=1,
        assets={
            "item.test": RegistryAsset(
                key="item.test",
                type="thumbnail",
                filename="test_item.png",
                sha256="b" * 64,
                width=256,
                height=256,
                size_bytes=1,
                channel_id="1",
                message_id="2",
                attachment_id="3",
                cdn_url="https://cdn.discordapp.com/attachments/1/3/test_item.png",
                uploaded_at="2026-07-04T00:00:00+00:00",
            )
        },
    )

    write_registry_atomic(registry, registry_path)

    assert json.loads(registry_path.read_text(encoding="utf-8"))["assets"]["item.test"]["sha256"] == "b" * 64
    assert registry_path.with_suffix(".json.bak").exists()


def test_thumbnail_and_banner_application_to_embed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    thumb = _write_png(project / "assets/discord/thumbnails/items/test_item.png", 256, 256)
    banner = _write_png(project / "assets/discord/locations/test_hall.png", 1200, 300)
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "item.test": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/test_item.png",
                    "alt_text": "A test item",
                    "required": False,
                },
                "location.test": {
                    "type": "location_banner",
                    "path": "assets/discord/locations/test_hall.png",
                    "alt_text": "A test hall",
                    "required": False,
                },
            },
        ),
        asset_root=project / "assets/discord",
    )
    registry = AssetRegistry(
        version=1,
        assets={
            "item.test": registry_asset_from_upload(
                key="item.test",
                definition=catalog.get("item.test"),
                image=inspect_image_file(thumb),
                channel_id=1,
                message_id=2,
                attachment_id=3,
                cdn_url="https://cdn.discordapp.com/attachments/1/3/test_item.png?ex=secret",
                uploaded_at=datetime(2026, 7, 4, tzinfo=UTC),
            ),
            "location.test": registry_asset_from_upload(
                key="location.test",
                definition=catalog.get("location.test"),
                image=inspect_image_file(banner),
                channel_id=1,
                message_id=4,
                attachment_id=5,
                cdn_url="https://cdn.discordapp.com/attachments/1/5/test_hall.png?hm=secret",
                uploaded_at=datetime(2026, 7, 4, tzinfo=UTC),
            ),
        },
    )
    service = DiscordAssetService(catalog=catalog, registry=registry, allow_local_fallback=False)
    embed = discord.Embed(title="Assets")

    service.apply_thumbnail(embed, "item.test")
    service.apply_banner(embed, "location.test")

    assert embed.thumbnail.url == "https://cdn.discordapp.com/attachments/1/3/test_item.png"
    assert embed.image.url == "attachment://test_hall.png"

    payload = service.message_payload_with_banner_attachment(embed)
    files = payload["files"]
    try:
        assert sorted(payload) == ["embed", "files"]
        assert payload["embed"].title == "Assets"
        assert payload["embed"].image.url is None
        assert payload["embed"].thumbnail.url == "https://cdn.discordapp.com/attachments/1/3/test_item.png"
        assert [file.filename for file in files] == ["test_hall.png"]
    finally:
        for file in files:
            file.close()


def test_message_payload_omits_none_view() -> None:
    service = DiscordAssetService(catalog=load_catalog(document={"version": 1, "assets": {}}), registry=AssetRegistry(version=1, assets={}))
    embed = discord.Embed(title="Report")
    view = discord.ui.View()

    without_view = service.message_payload_with_banner_attachment(embed, view=None)
    with_view = service.message_payload_with_banner_attachment(embed, view=view)

    assert "view" not in without_view
    assert with_view["view"] is view


def test_development_fallback_uses_local_attachments_for_unregistered_images(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_png(project / "assets/discord/locations/test_hall.png", 1200, 300)
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "location.test": {
                    "type": "location_banner",
                    "path": "assets/discord/locations/test_hall.png",
                    "alt_text": "A test hall",
                    "required": True,
                }
            },
        ),
        asset_root=project / "assets/discord",
    )
    service = DiscordAssetService(
        catalog=catalog,
        registry=AssetRegistry(version=1, assets={}),
        environment="development",
    )
    embed = discord.Embed(title="No registry yet")

    service.apply_banner(embed, "location.test")

    assert embed.image.url == "attachment://test_hall.png"
    payload = service.message_payload_with_banner_attachment(embed)
    files = payload["files"]
    try:
        assert payload["embed"].title == "No registry yet"
        assert payload["embed"].image.url is None
        assert [file.filename for file in files] == ["test_hall.png"]
    finally:
        for file in files:
            file.close()


def test_malicious_relative_paths_are_rejected(tmp_path: Path) -> None:
    project = _project(tmp_path)
    catalog_path = _write_catalog(
        project,
        {
            "item.bad": {
                "type": "thumbnail",
                "path": "assets/discord/../secrets/token.png",
                "alt_text": "Bad",
                "required": False,
            }
        },
    )

    with pytest.raises(ValueError, match="path must stay inside"):
        load_catalog(catalog_path, asset_root=project / "assets/discord")


def test_gameplay_data_referencing_unknown_asset_key_fails(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_png(project / "assets/discord/thumbnails/items/test_item.png", 256, 256)
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "item.test": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/test_item.png",
                    "alt_text": "A test item",
                    "required": False,
                }
            },
        ),
        asset_root=project / "assets/discord",
    )
    content_dir = project / "bot/content"
    (content_dir / "equipment.json").write_text('[{"thumbnail_asset":"item.missing"}]', encoding="utf-8")

    with pytest.raises(ValueError, match="unknown image assets"):
        validate_gameplay_asset_references(catalog, content_dir)


@pytest.mark.asyncio
async def test_sync_uploads_changed_assets_with_mock_channel(tmp_path: Path) -> None:
    project = _project(tmp_path)
    image_path = _write_png(project / "assets/discord/thumbnails/items/test_item.png", 256, 256)
    catalog = load_catalog(
        _write_catalog(
            project,
            {
                "item.test": {
                    "type": "thumbnail",
                    "path": "assets/discord/thumbnails/items/test_item.png",
                    "alt_text": "A test item",
                    "required": False,
                }
            },
        ),
        asset_root=project / "assets/discord",
    )
    planned, _summary = plan_sync(catalog, AssetRegistry(version=1, assets={}))
    channel = FakeChannel()

    registry = await sync_registry_with_channel(channel, planned, AssetRegistry(version=1, assets={}))

    assert len(channel.sent) == 1
    assert "Key: item.test" in channel.sent[0]["content"]
    assert channel.sent[0]["file"].filename == "test_item.png"
    assert registry.get("item.test").sha256 == inspect_image_file(image_path).sha256
    assert "?" not in registry.get("item.test").cdn_url


class FakeAttachment:
    id = 300
    url = "https://cdn.discordapp.com/attachments/100/300/test_item.png?ex=temporary"


class FakeMessage:
    id = 200
    attachments = [FakeAttachment()]


class FakeChannel:
    id = 100

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, *, content: str, file) -> FakeMessage:
        self.sent.append({"content": content, "file": file})
        return FakeMessage()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "bot/content").mkdir(parents=True)
    (project / "assets/discord/thumbnails/items").mkdir(parents=True)
    (project / "assets/discord/locations").mkdir(parents=True)
    return project


def _write_catalog(project: Path, assets: dict[str, dict[str, object]]) -> Path:
    path = project / "bot/content/image_assets.json"
    path.write_text(json.dumps({"version": 1, "assets": assets}, indent=2), encoding="utf-8")
    return path


def _write_png(path: Path, width: int, height: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(height):
        line = bytearray()
        for x in range(width):
            line.extend(((x + y) % 255, (x * 2) % 255, (y * 3) % 255))
        rows.append(bytes(line))
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(raw, 9))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)
    return path
