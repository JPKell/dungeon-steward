from __future__ import annotations

import random
from datetime import timedelta

import pytest

from bot.models import WeeklyObjective, WeeklyObjectiveReward
from bot.services.weekly_objective_service import (
    MAX_DIFFICULTY_INDEX,
    MIN_DIFFICULTY_INDEX,
    OBJECTIVE_TEMPLATES,
    ObjectiveMode,
    WeeklyMetric,
    WeeklyObjectiveService,
    calculate_reward_preview,
    minimum_required_contribution,
    reference_equipment_cost,
    render_description,
    round_target,
)
from tests.conftest import make_player


def _objective(db, now, *, guild_id=10, metric=WeeklyMetric.EXPLORATIONS, target=10, difficulty=1.0, participants=1):
    objective = WeeklyObjective(
        guild_id=guild_id,
        objective_key=f"test_{metric.value}",
        title=f"Test {metric.value}",
        description="Test objective.",
        target_value=target,
        progress_value=0,
        reward_gold=0,
        starts_at=now,
        ends_at=now + timedelta(days=7),
        metric=metric.value,
        mode=ObjectiveMode.MIXED.value,
        effort_tier=3,
        difficulty_index=difficulty,
        previous_participant_count=participants,
        participant_factor=1.0,
        raw_target_value=float(target),
        rounded_target_value=target,
        schema_version=2,
        reward_policy_version=1,
    )
    db.add(objective)
    db.flush()
    return objective


def test_weekly_templates_are_complete_and_valid():
    keys = [template.key for template in OBJECTIVE_TEMPLATES]

    assert len(OBJECTIVE_TEMPLATES) == 50
    assert len(set(keys)) == 50
    for template in OBJECTIVE_TEMPLATES:
        assert "{target}" in template.description_template
        assert isinstance(template.metric, WeeklyMetric)
        assert isinstance(template.mode, ObjectiveMode)
        assert template.base_target > 0
        assert 1 <= template.effort_tier <= 5


def test_weekly_description_renderer_formats_and_rejects_bad_tokens():
    assert render_description("Earn {target} gold.", target=2500) == "Earn 2,500 gold."

    with pytest.raises(ValueError):
        render_description("Earn gold.", target=2500)
    with pytest.raises(ValueError):
        render_description("Earn {target} gold from {place}.", target=2500)
    with pytest.raises(ValueError):
        render_description("Earn {target} gold.")


def test_weekly_events_only_increment_matching_objective_and_are_idempotent(db, now):
    service = WeeklyObjectiveService()
    objective = _objective(db, now, metric=WeeklyMetric.EXPLORE_GOLD, target=100)
    player = make_player(db, now=now, guild_id=10)

    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORE_XP,
        amount=50,
        event_id="wrong",
        source="test",
    )
    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORE_GOLD,
        amount=40,
        event_id="gold-1",
        source="test",
    )
    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORE_GOLD,
        amount=40,
        event_id="gold-1",
        source="test",
    )

    assert objective.progress_value == 40
    assert service.player_contribution(db, objective, player_id=player.id) == 40


def test_weekly_exploration_routes_influence_stability_and_discoveries(db, now):
    service = WeeklyObjectiveService()
    player = make_player(db, now=now, guild_id=10)

    for metric, expected in (
        (WeeklyMetric.HERO_INFLUENCE_GAINED, 3),
        (WeeklyMetric.HERO_INFLUENCE_REDUCED, 4),
        (WeeklyMetric.VILLAIN_INFLUENCE_GAINED, 5),
        (WeeklyMetric.VILLAIN_INFLUENCE_REDUCED, 6),
        (WeeklyMetric.STABILITY_GAINED, 7),
        (WeeklyMetric.DISCOVERIES_FOUND, 1),
    ):
        objective = _objective(db, now, metric=metric, target=20)
        service.record_exploration_result(
            db,
            guild_id=10,
            user_id=player.discord_user_id,
            event_id=f"explore-{metric.value}",
            gold=10,
            xp=11,
            hero_delta=3 if metric == WeeklyMetric.HERO_INFLUENCE_GAINED else -4,
            villain_delta=5 if metric == WeeklyMetric.VILLAIN_INFLUENCE_GAINED else -6,
            stability_delta=7 if metric == WeeklyMetric.STABILITY_GAINED else -8,
            discovery_key="odd_scroll" if metric == WeeklyMetric.DISCOVERIES_FOUND else None,
            new_discovery=True,
        )
        assert objective.progress_value == expected
        objective.resolved_at = now


def test_weekly_unique_discoveries_are_deduped_per_objective(db, now):
    service = WeeklyObjectiveService()
    player = make_player(db, now=now, guild_id=10)
    first = _objective(db, now, metric=WeeklyMetric.UNIQUE_DISCOVERIES_FOUND, target=5)

    for suffix in ("a", "b"):
        service.record_exploration_result(
            db,
            guild_id=10,
            user_id=player.discord_user_id,
            event_id=f"unique-{suffix}",
            gold=0,
            xp=0,
            hero_delta=0,
            villain_delta=0,
            stability_delta=0,
            discovery_key="same_key",
            new_discovery=True,
        )
    assert first.progress_value == 1

    first.resolved_at = now
    second = _objective(db, now + timedelta(days=8), metric=WeeklyMetric.UNIQUE_DISCOVERIES_FOUND, target=5)
    service.record_exploration_result(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        event_id="unique-next",
        gold=0,
        xp=0,
        hero_delta=0,
        villain_delta=0,
        stability_delta=0,
        discovery_key="same_key",
        new_discovery=True,
    )
    assert second.progress_value == 1


def test_weekly_defense_routes_aggregate_metrics(db, now):
    service = WeeklyObjectiveService()
    player = make_player(db, now=now, guild_id=10)
    objective = _objective(db, now, metric=WeeklyMetric.DEFENSE_XP, target=500)
    report = type("Report", (), {"session_id": "def-1", "victories": 3, "gold_earned": 40, "combat_xp_earned": 55})()

    service.record_defense_result(db, guild_id=10, user_id=player.discord_user_id, report=report)
    service.record_defense_result(db, guild_id=10, user_id=player.discord_user_id, report=report)

    assert objective.progress_value == 55


def test_weekly_targets_scale_and_round_by_metric():
    assert round_target(1234, metric=WeeklyMetric.EXPLORE_GOLD, round_to=1, minimum=1) == 1250
    assert round_target(123, metric=WeeklyMetric.EXPLORE_XP, round_to=1, minimum=1) == 120
    assert round_target(2.1, metric=WeeklyMetric.EXPLORATIONS, round_to=1, minimum=10) == 10


def test_weekly_creation_uses_previous_participants_and_difficulty(db, now):
    service = WeeklyObjectiveService()
    previous = _objective(db, now - timedelta(days=8), metric=WeeklyMetric.EXPLORATIONS, target=10)
    previous.resolved_at = now - timedelta(days=1)
    previous.participant_count = 5
    dungeon = service.players.get_or_create_guild(db, guild_id=10)
    dungeon.weekly_difficulty_index = 1.5

    objective = service.create_next(db, guild_id=10, now=now, rng=random.Random(1))

    assert objective.previous_participant_count == 5
    assert objective.participant_factor > 1
    assert objective.difficulty_index == 1.5
    assert objective.target_value >= int(objective.raw_target_value * 0.65)


def test_weekly_success_and_failure_adjust_difficulty_bounds(db, now):
    service = WeeklyObjectiveService()
    player = make_player(db, now=now, guild_id=10)
    dungeon = service.players.get_or_create_guild(db, guild_id=10)
    dungeon.weekly_difficulty_index = 1.0
    success = _objective(db, now, metric=WeeklyMetric.EXPLORATIONS, target=1)

    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORATIONS,
        amount=1,
        event_id="success",
        source="test",
    )
    assert success.succeeded is True
    assert dungeon.weekly_difficulty_index == pytest.approx(1.1)

    dungeon.weekly_difficulty_index = MIN_DIFFICULTY_INDEX
    failure = _objective(db, now - timedelta(days=8), metric=WeeklyMetric.EXPLORATIONS, target=10)
    failure.ends_at = now - timedelta(days=1)
    service.resolve_if_due(db, failure, now=now)
    assert failure.succeeded is False
    assert dungeon.weekly_difficulty_index == MIN_DIFFICULTY_INDEX

    dungeon.weekly_difficulty_index = MAX_DIFFICULTY_INDEX
    capped = _objective(db, now, metric=WeeklyMetric.EXPLORATIONS, target=1)
    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORATIONS,
        amount=1,
        event_id="cap",
        source="test",
    )
    assert capped.succeeded is True
    assert dungeon.weekly_difficulty_index == MAX_DIFFICULTY_INDEX


def test_weekly_rewards_use_equipment_reference_and_are_idempotent(db, now):
    service = WeeklyObjectiveService()
    player = make_player(db, now=now, guild_id=10)
    player.explore_level = 1
    objective = _objective(db, now, metric=WeeklyMetric.EXPLORATIONS, target=1, difficulty=1.0, participants=1)

    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORATIONS,
        amount=1,
        event_id="reward",
        source="test",
    )
    first_gold = player.gold
    service.process_rewards(db, objective, now=now)

    reward = db.query(WeeklyObjectiveReward).one()
    assert reward.gold_awarded == first_gold
    assert player.gold == first_gold
    assert reward.reference_equipment_cost == reference_equipment_cost(player.explore_level)
    assert calculate_reward_preview(1, effort_tier=3, difficulty_index=1.0).gold_awarded <= max(
        200,
        int(reference_equipment_cost(1) * 0.6),
    )


def test_weekly_failed_objectives_do_not_pay_and_minimum_contribution_filters(db, now):
    service = WeeklyObjectiveService()
    player = make_player(db, now=now, guild_id=10)
    objective = _objective(db, now, metric=WeeklyMetric.EXPLORE_GOLD, target=5000, participants=1)

    assert minimum_required_contribution(objective) == 50
    service.record_weekly_metric(
        db,
        guild_id=10,
        user_id=player.discord_user_id,
        metric=WeeklyMetric.EXPLORE_GOLD,
        amount=10,
        event_id="too-small",
        source="test",
    )
    objective.ends_at = now - timedelta(seconds=1)
    service.resolve_if_due(db, objective, now=now)

    assert objective.succeeded is False
    assert db.query(WeeklyObjectiveReward).count() == 0
    assert player.gold == 0


def test_weekly_selection_avoids_recent_template_metric_and_mode(db, now):
    service = WeeklyObjectiveService()
    for index, template in enumerate(OBJECTIVE_TEMPLATES[:12]):
        objective = _objective(db, now - timedelta(days=20 - index), metric=template.metric, target=template.base_target)
        objective.objective_key = template.key
        objective.mode = template.mode.value
        objective.resolved_at = now - timedelta(days=12 - index)
    chosen = service.select_template(db, guild_id=10, rng=random.Random(2))

    assert chosen.key not in {template.key for template in OBJECTIVE_TEMPLATES[:12]}
    recent_metrics = {
        objective.metric
        for objective in db.query(WeeklyObjective).order_by(WeeklyObjective.resolved_at.desc()).limit(4)
    }
    assert chosen.metric.value not in recent_metrics
