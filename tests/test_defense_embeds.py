from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import bot.utils.defense_embeds as defense_embeds
from bot.services.defense_service import DefenseReport, StartedDefense
from bot.services.discord_asset_service import AssetCatalog, AssetDefinition, AssetRegistry, DiscordAssetService, RegistryAsset
from bot.services.discord_emoji_service import DiscordEmojiService, EmojiCatalog, EmojiDefinition, EmojiRegistry, EmojiRegistryEntry
from bot.services.equipment_service import CombatStats
from bot.utils.defense_embeds import build_defense_report_embed, build_defense_started_embed


def test_defense_report_embed_hides_unneeded_resolution_details() -> None:
    report = DefenseReport(
        player_id=1,
        session_id="session",
        dungeon_level=3,
        started_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        ended_at=datetime(2026, 7, 3, 12, 5, tzinfo=UTC),
        reason="duration cap",
        elapsed_seconds=300,
        capped_seconds=240,
        scheduled_battles=5,
        completed_battles=4,
        victories=2,
        defeats=1,
        draws=1,
        unresolved_attacks=1,
        combat_xp_earned=24,
        gold_earned=12,
        combat_levels_gained=1,
        stat_points_earned=2,
        starting_hp=20,
        ending_hp=8,
        max_hp=24,
        enemies_encountered={"Slime": 2},
        notable_battles=("Round 1: Scout beat Slime.",),
    )

    response = build_defense_report_embed(report)
    fields = {field.name: field.value for field in response.fields}

    assert fields["Battles"] == "Scheduled: 5\nCompleted: 4"
    assert fields["Results"] == "Victories: 2\nDefeats: 1"
    assert "Unresolved" not in fields["Battles"]
    assert "Draws" not in fields["Results"]
    assert "Notable Battles" not in fields


def test_defense_report_embed_uses_enemy_emoji_and_thumbnail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        defense_embeds,
        "ENEMY_TYPES",
        {
            "slime": {
                "name": "Slime",
                "thumbnail_asset": "enemy.slime",
                "emoji_asset": "enemy.slime",
            },
            "bat": {"name": "Bat"},
        },
    )
    report = _report(enemies_encountered={"Slime": 2, "Bat": 1})

    response = build_defense_report_embed(
        report,
        asset_service=_asset_service(tmp_path),
        emoji_service=_emoji_service(tmp_path),
    )
    fields = {field.name: field.value for field in response.fields}

    assert response.thumbnail.url == "https://cdn.discordapp.com/attachments/1/3/slime.webp"
    assert fields["Enemies Encountered"] == "<:ds_e_slime:123456789> **Slime**: 2\n**Bat**: 1"


def test_defense_started_embed_uses_dungeon_thumbnail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(defense_embeds, "DUNGEON_LEVELS", {3: {"thumbnail_asset": "enemy.slime"}})
    started = StartedDefense(
        player_id=1,
        session_id="session",
        dungeon_level=3,
        started_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        max_ends_at=datetime(2026, 7, 3, 13, 0, tzinfo=UTC),
        current_hp=20,
        stats=CombatStats(max_hp=24, attack=5, defense=4, speed=3),
    )

    response = build_defense_started_embed(started, asset_service=_asset_service(tmp_path))

    assert response.thumbnail.url == "https://cdn.discordapp.com/attachments/1/3/slime.webp"


def _report(*, enemies_encountered: dict[str, int]) -> DefenseReport:
    started_at = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    return DefenseReport(
        player_id=1,
        session_id="session",
        dungeon_level=3,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        reason="duration cap",
        elapsed_seconds=300,
        capped_seconds=240,
        scheduled_battles=5,
        completed_battles=4,
        victories=2,
        defeats=1,
        draws=1,
        unresolved_attacks=1,
        combat_xp_earned=24,
        gold_earned=12,
        combat_levels_gained=1,
        stat_points_earned=2,
        starting_hp=20,
        ending_hp=8,
        max_hp=24,
        enemies_encountered=enemies_encountered,
        notable_battles=("Round 1: Scout beat Slime.",),
    )


def _asset_service(tmp_path: Path) -> DiscordAssetService:
    slime = _asset_definition(tmp_path, "enemy.slime", "thumbnail", "slime.webp")
    defending = _asset_definition(tmp_path, "location.defending_the_dungeon", "location_banner", "defending.webp")
    returned = _asset_definition(tmp_path, "location.returned_from_dungeon", "location_banner", "returned.webp")
    return DiscordAssetService(
        catalog=AssetCatalog(
            version=1,
            assets={
                "enemy.slime": slime,
                "location.defending_the_dungeon": defending,
                "location.returned_from_dungeon": returned,
            },
        ),
        registry=AssetRegistry(
            version=1,
            assets={
                "enemy.slime": RegistryAsset(
                    key="enemy.slime",
                    type="thumbnail",
                    filename="slime.webp",
                    sha256="a" * 64,
                    width=256,
                    height=256,
                    size_bytes=1,
                    channel_id="1",
                    message_id="2",
                    attachment_id="3",
                    cdn_url="https://cdn.discordapp.com/attachments/1/3/slime.webp",
                    uploaded_at="2026-07-04T00:00:00+00:00",
                )
            },
        ),
        allow_local_fallback=False,
    )


def _asset_definition(tmp_path: Path, key: str, asset_type: str, filename: str) -> AssetDefinition:
    return AssetDefinition(
        key=key,
        type=asset_type,
        path=tmp_path / filename,
        alt_text=key,
        required=False,
    )


def _emoji_service(tmp_path: Path) -> DiscordEmojiService:
    return DiscordEmojiService(
        catalog=EmojiCatalog(
            version=1,
            emojis={
                "enemy.slime": EmojiDefinition(
                    key="enemy.slime",
                    name="ds_e_slime",
                    path=tmp_path / "slime.png",
                    alt_text="Slime",
                )
            },
        ),
        registry=EmojiRegistry(
            version=1,
            emojis={
                "enemy.slime": EmojiRegistryEntry(
                    key="enemy.slime",
                    name="ds_e_slime",
                    emoji_id="123456789",
                    sha256="b" * 64,
                    animated=False,
                    uploaded_at="2026-07-04T00:00:00+00:00",
                )
            },
        ),
    )
