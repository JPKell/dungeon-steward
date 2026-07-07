from __future__ import annotations

from datetime import UTC, datetime

from bot.services.defense_service import DefenseReport
from bot.utils.defense_embeds import build_defense_report_embed


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
