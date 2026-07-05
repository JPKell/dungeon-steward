from __future__ import annotations

import random
from dataclasses import replace
from datetime import timedelta

import pytest

import bot.services.defense_service as defense_module
import bot.services.progression_service as progression_service
from bot.config import MAX_ENERGY
from bot.services.defense_service import AlreadyDefendingError, DefenseService
from bot.services.enemy_service import DUNGEON_LEVELS, ENEMY_TYPES, GeneratedEnemy, generate_enemy, validate_enemy_definitions
from bot.services.energy_service import EnergyService
from bot.services.equipment_service import EquipmentService, get_effective_combat_stats
from bot.services.progression_content import PROGRESSION_CONTENT, ExploreLevelingProgression, ScalingProgression
from bot.services.progression_service import (
    allocate_stat_points,
    calculate_combat_power,
    calculate_explore_level,
    calculate_max_hp,
    calculate_scaling_amount,
    get_explore_cooldown_minutes,
    get_explore_xp_to_next_level,
    get_hp_gain_for_combat_level,
    get_max_defense_minutes,
    get_stat_points_for_combat_level,
    grant_combat_xp,
    scale_exploration_gold,
    scale_exploration_xp,
    scale_shop_item_cost,
    scale_shop_item_stat,
)
from bot.services.shop_service import ShopService
from tests.conftest import make_player


def test_new_players_get_combat_defaults(db, now):
    player = make_player(db, now=now)
    assert player.explore_level == 1
    assert player.combat_level == 1
    assert player.combat_xp == 0
    assert player.combat_xp_to_next_level == progression_service.get_combat_xp_to_next_level(1)
    assert player.unspent_stat_points == 0
    assert player.current_hp == PROGRESSION_CONTENT.new_player.base_hp
    assert player.max_hp == PROGRESSION_CONTENT.new_player.base_hp
    assert player.attack == 5
    assert player.defense == 5
    assert player.speed == 5
    assert player.weapon is None
    assert player.highest_unlocked_dungeon_level == 1
    assert player.highest_completed_dungeon_level == 1
    assert player.defense_wins == 0


def test_explore_cooldown_scales_to_floor():
    assert get_explore_cooldown_minutes(1) == 120
    assert get_explore_cooldown_minutes(2) == 119
    assert get_explore_cooldown_minutes(999) == 30


def test_default_explore_leveling_uses_tuned_quadratic_formula():
    assert get_explore_xp_to_next_level(1) == 72
    assert get_explore_xp_to_next_level(2) == 83
    assert calculate_explore_level(0) == 1
    assert calculate_explore_level(71) == 1
    assert calculate_explore_level(72) == 2
    assert calculate_explore_level(154) == 2
    assert calculate_explore_level(155) == 3


def test_quadratic_explore_leveling_curve():
    leveling = ExploreLevelingProgression(
        curve="quadratic",
        base_xp=100,
        linear_growth=25,
        quadratic_growth=25,
        exponential_growth=1.15,
        max_level=0,
    )
    assert get_explore_xp_to_next_level(1, leveling) == 100
    assert get_explore_xp_to_next_level(2, leveling) == 150
    assert get_explore_xp_to_next_level(3, leveling) == 250
    assert calculate_explore_level(249, leveling) == 2
    assert calculate_explore_level(250, leveling) == 3


def test_exponential_explore_leveling_curve():
    leveling = ExploreLevelingProgression(
        curve="exponential",
        base_xp=100,
        linear_growth=0,
        quadratic_growth=0,
        exponential_growth=1.5,
        max_level=0,
    )
    assert get_explore_xp_to_next_level(1, leveling) == 100
    assert get_explore_xp_to_next_level(2, leveling) == 150
    assert get_explore_xp_to_next_level(3, leveling) == 225
    assert calculate_explore_level(474, leveling) == 3
    assert calculate_explore_level(475, leveling) == 4


def test_generic_scaling_amount_supports_curve_types():
    linear = ScalingProgression("linear", 2, 3, 0, 1.0, 0)
    quadratic = ScalingProgression("quadratic", 2, 3, 4, 1.0, 0)
    exponential = ScalingProgression("exponential", 2, 0, 0, 2.0, 0)
    assert calculate_scaling_amount(3, linear) == 8
    assert calculate_scaling_amount(3, quadratic) == 24
    assert calculate_scaling_amount(3, exponential) == 8


def test_exploration_reward_scaling_uses_tuned_growth():
    assert scale_exploration_gold(100, 1) == 115
    assert scale_exploration_gold(100, 110) > scale_exploration_gold(100, 91)
    assert scale_exploration_xp(100, 20) > 100


def test_shop_scaling_defaults_preserve_base_items():
    assert scale_shop_item_cost(100, 20) == 100
    assert scale_shop_item_stat(7, 20) == 7


def test_shop_scaling_uses_shared_curve_helpers(monkeypatch):
    content = progression_service.PROGRESSION_CONTENT
    monkeypatch.setattr(
        progression_service,
        "PROGRESSION_CONTENT",
        replace(
            content,
            shop=replace(
                content.shop,
                cost_multiplier=ScalingProgression("linear", 1.0, 0.5, 0.0, 1.0, 0.01),
                stat_multiplier=ScalingProgression("linear", 1.0, 0.5, 0.0, 1.0, 0.0),
            ),
        ),
    )
    equipment = EquipmentService()
    item = next(item for item in equipment.items if item.attack > 0)

    scaled = equipment.scaled_for_combat_level(item, 3)

    assert scaled.cost == item.cost * 2
    assert scaled.attack == item.attack * 2
    assert scaled.hp == item.hp * 2


def test_energy_uses_explore_level_cooldown(db, now):
    player = make_player(db, now=now - timedelta(minutes=119))
    player.energy = 1
    player.explore_level = 2
    state = EnergyService().recalculate(player, now=now)
    assert state.energy == 2


def test_combat_xp_can_gain_multiple_levels(db, now):
    player = make_player(db, now=now)
    amount = progression_service.get_combat_xp_to_next_level(1) + progression_service.get_combat_xp_to_next_level(2)
    levels, points = grant_combat_xp(player, amount)
    assert levels == 2
    assert points == 2
    assert player.combat_level == 3
    assert player.unspent_stat_points == 2
    assert player.max_hp == calculate_max_hp(3)
    assert player.current_hp == player.max_hp


def test_combat_hp_and_stat_point_scaling_defaults():
    assert get_hp_gain_for_combat_level(1) == 0
    assert get_hp_gain_for_combat_level(2) == 2
    assert get_hp_gain_for_combat_level(3) == 2
    assert get_hp_gain_for_combat_level(25) == 7
    assert get_stat_points_for_combat_level(1) == 0
    assert get_stat_points_for_combat_level(2) == 1
    assert get_stat_points_for_combat_level(3) == 1
    assert get_stat_points_for_combat_level(20) == 2


def test_stat_allocation_spends_points_atomically(db, now):
    player = make_player(db, now=now)
    player.unspent_stat_points = 3
    allocate_stat_points(player, "attack", 2)
    assert player.attack == 7
    assert player.unspent_stat_points == 1
    with pytest.raises(ValueError):
        allocate_stat_points(player, "speed", 2)


def test_defense_duration_caps():
    assert get_max_defense_minutes(1) == 60
    assert get_max_defense_minutes(2) == 61
    assert get_max_defense_minutes(421) == 480


def test_enemy_definitions_cover_all_levels():
    validate_enemy_definitions()
    assert len(DUNGEON_LEVELS) == 20
    assert len(ENEMY_TYPES) >= 20
    enemy = generate_enemy(10, rng=random.Random(7))
    assert enemy.current_hp == enemy.max_hp
    assert enemy.combat_xp > 0
    assert enemy.gold >= 0


def test_defense_resolves_completed_minutes_and_rewards(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    starting_gold = player.gold
    player.current_hp = 200
    player.max_hp = 200
    player.attack = 80
    player.defense = 80
    player.speed = 80
    service = DefenseService()
    started = service.start(
        db,
        guild_id=10,
        user_id=1,
        display_name="Scout",
        dungeon_level=1,
        now=now,
    )
    assert started.current_hp == 200

    report = service.stop(
        db,
        guild_id=10,
        user_id=1,
        now=now + timedelta(minutes=3, seconds=59),
        rng=random.Random(3),
    )
    assert report.scheduled_battles == 3
    assert report.completed_battles == 3
    assert report.victories == 3
    assert report.combat_xp_earned > 0
    assert report.gold_earned >= 0
    assert player.gold == starting_gold + report.gold_earned
    assert player.defense_wins == report.victories
    assert player.highest_completed_dungeon_level >= 1
    assert not player.is_defending


def test_defense_prevents_duplicate_active_session(db, now):
    service = DefenseService()
    service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=1, now=now)
    with pytest.raises(AlreadyDefendingError):
        service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=1, now=now)


def test_defense_ends_with_full_hp(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.highest_unlocked_dungeon_level = 20
    player.highest_completed_dungeon_level = 20
    player.current_hp = 1
    player.max_hp = 50
    player.attack = 1
    player.defense = 0
    player.speed = 1
    service = DefenseService()
    service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=20, now=now)
    report = service.stop(
        db,
        guild_id=10,
        user_id=1,
        now=now + timedelta(minutes=5),
        rng=random.Random(11),
    )
    assert report.scheduled_battles == 5
    assert report.completed_battles == 1
    assert report.unresolved_attacks == 4
    assert report.defeats == 1
    assert report.ending_hp == 0
    assert report.max_hp == player.max_hp
    assert not player.is_defending
    assert player.current_hp == player.max_hp


def test_defense_report_ending_hp_precedes_equipped_full_recovery(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.highest_unlocked_dungeon_level = 20
    player.highest_completed_dungeon_level = 20
    player.current_hp = 1
    player.max_hp = 50
    player.attack = 1
    player.defense = 0
    player.speed = 1
    equipment = EquipmentService()
    item = next(item for item in equipment.eligible_for_level(player.combat_level) if item.hp > 0)
    setattr(player, item.slot, item.key)
    effective_hp = get_effective_combat_stats(player).max_hp

    service = DefenseService()
    service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=20, now=now)
    report = service.stop(
        db,
        guild_id=10,
        user_id=1,
        now=now + timedelta(minutes=5),
        rng=random.Random(11),
    )

    assert report.defeats == 1
    assert report.ending_hp == 0
    assert report.max_hp == effective_hp
    assert player.current_hp == effective_hp
    assert player.current_hp > player.max_hp


def test_explore_guard_resolves_active_defense(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.energy = MAX_ENERGY
    player.current_hp = 200
    player.max_hp = 200
    player.attack = 80
    player.defense = 80
    player.speed = 80
    service = DefenseService()
    service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=1, now=now)
    report = service.resolve_before_explore(
        db,
        guild_id=10,
        user_id=1,
        display_name="Scout",
        now=now + timedelta(minutes=2),
        rng=random.Random(5),
    )
    assert report is not None
    assert report.reason == "exploration"
    assert report.scheduled_battles == 2
    assert not player.is_defending


def test_xp_potion_does_not_apply_to_prior_defense_minutes(db, now, monkeypatch):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.current_hp = 200
    player.max_hp = 200
    player.attack = 80
    player.defense = 80
    player.speed = 80
    enemy_power = calculate_combat_power(max_hp=200, attack=80, defense=80, speed=80)
    enemy = GeneratedEnemy(
        key="training_dummy",
        name="Training Dummy",
        rank="common",
        dungeon_level=1,
        level=1,
        max_hp=1,
        current_hp=1,
        attack=0,
        defense=0,
        speed=1,
        gold=0,
        combat_xp=100,
        power=enemy_power,
        max_gold=0,
        max_combat_xp=100,
    )
    monkeypatch.setattr(defense_module, "generate_enemy", lambda dungeon_level, rng: enemy)

    service = DefenseService()
    service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=1, now=now)
    service.potions.add_drop(db, player, "potion_xp_01")
    service.potions.consume(
        db,
        player,
        "potion_xp_01",
        idempotency_token="mid-defense",
        now=now + timedelta(minutes=2, seconds=1),
    )

    report = service.stop(db, guild_id=10, user_id=1, now=now + timedelta(minutes=4))

    assert report.completed_battles == 4
    assert report.potion_bonus_combat_xp == 8


def test_expired_defense_resolves_lazily(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.current_hp = 200
    player.max_hp = 200
    player.attack = 80
    player.defense = 80
    player.speed = 80
    service = DefenseService()
    service.start(db, guild_id=10, user_id=1, display_name="Scout", dungeon_level=1, now=now)
    report = service.resolve_if_expired(
        db,
        player,
        now=now + timedelta(minutes=60),
        rng=random.Random(9),
    )
    assert report is not None
    assert report.reason == "duration cap"
    assert report.scheduled_battles == 60
    assert not player.is_defending


def test_shop_stock_is_deterministic_by_hour_and_combat_level(db, now):
    player_a = make_player(db, now=now, user_id=1, guild_id=10)
    player_b = make_player(db, now=now, user_id=2, guild_id=10)
    player_a.combat_level = 8
    player_b.combat_level = 8
    shop = ShopService()

    stock_a = shop.stock_for_player(player_a, now=now.replace(minute=17))
    stock_b = shop.stock_for_player(player_b, now=now.replace(minute=45))
    next_hour_stock = shop.stock_for_player(player_a, now=now + timedelta(hours=1))

    assert [item.key for item in stock_a.items] == [item.key for item in stock_b.items]
    assert [item.key for item in stock_a.items] != [item.key for item in next_hour_stock.items]
    assert len(stock_a.items) == 10
    assert all(item.min_level <= 8 <= item.max_level for item in stock_a.items)


def test_shop_purchase_equips_item_and_applies_bonuses(db, now):
    player = make_player(db, now=now, user_id=1, guild_id=10)
    player.gold = 10_000
    player.combat_level = 1
    shop = ShopService()
    stock = shop.stock_for_player(player, now=now)
    purchase = shop.purchase(
        db,
        guild_id=10,
        user_id=1,
        display_name="Scout",
        stock_number=1,
        now=now,
    )
    assert purchase.item.key == stock.items[0].key
    assert getattr(player, purchase.item.slot) == purchase.item.key
    assert player.gold == 10_000 - purchase.item.cost

    stats = get_effective_combat_stats(player)
    assert stats.max_hp == player.max_hp + purchase.item.hp
    assert stats.attack == player.attack + purchase.item.attack
    assert stats.defense == player.defense + purchase.item.defense
    assert stats.speed == player.speed + purchase.item.speed


def test_equipment_service_reads_equipped_names(db, now):
    player = make_player(db, now=now)
    equipment = EquipmentService()
    item = equipment.items[0]
    setattr(player, item.slot, item.key)
    equipped = equipment.get_player_equipment(player)
    assert equipped[item.slot] == item
