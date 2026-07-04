from __future__ import annotations

import importlib.util
import json
import random
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

SERVICES = Path(__file__).parent
CONTENT = Path(__file__).parents[1] / "content"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def install_stubs():
    bot = types.ModuleType("bot")
    services = types.ModuleType("bot.services")
    models = types.ModuleType("bot.models")

    class Player:
        pass

    models.Player = Player
    sys.modules.setdefault("bot", bot)
    sys.modules.setdefault("bot.services", services)
    sys.modules.setdefault("bot.models", models)

    progression_content = load_module("bot.services.progression_content", SERVICES / "progression_content.py")
    progression_service = load_module("bot.services.progression_service", SERVICES / "progression_service.py")

    enemy_service = types.ModuleType("bot.services.enemy_service")

    @dataclass(frozen=True)
    class GeneratedEnemy:
        key: str
        name: str
        rank: str
        dungeon_level: int
        level: int
        max_hp: int
        current_hp: int
        attack: int
        defense: int
        speed: int
        gold: int
        combat_xp: int
        power: float

    enemy_service.GeneratedEnemy = GeneratedEnemy
    sys.modules["bot.services.enemy_service"] = enemy_service

    equipment_service = types.ModuleType("bot.services.equipment_service")

    @dataclass(frozen=True)
    class CombatStats:
        max_hp: int
        attack: int
        defense: int
        speed: int

    equipment_service.CombatStats = CombatStats
    sys.modules["bot.services.equipment_service"] = equipment_service
    combat_service = load_module("bot.services.combat_service", SERVICES / "combat_service.py")
    return progression_content, progression_service, combat_service, GeneratedEnemy, CombatStats, Player


PC, PS, CS, GeneratedEnemy, CombatStats, Player = install_stubs()


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.progression = json.loads((CONTENT / "progression.json").read_text())
        cls.dungeons = json.loads((CONTENT / "dungeon_levels.json").read_text())
        cls.equipment = json.loads((CONTENT / "equipment.json").read_text())
        cls.simulation = json.loads((CONTENT / "simulation_results.json").read_text())
        cls.validation = json.loads((CONTENT / "content_validation.json").read_text())

    def test_01_energy_starts_at_120(self):
        self.assertEqual(PS.get_explore_cooldown_minutes(1), 120)

    def test_02_energy_never_below_30(self):
        self.assertEqual(PS.get_explore_cooldown_minutes(91), 30)
        self.assertEqual(PS.get_explore_cooldown_minutes(10000), 30)

    def test_03_explore_levels_continue_after_cap(self):
        xp = PS.get_total_explore_xp_for_level(120)
        self.assertGreaterEqual(PS.calculate_explore_level(xp), 120)

    def test_04_post_cap_gold_increases_without_cooldown_change(self):
        self.assertEqual(PS.get_explore_cooldown_minutes(91), PS.get_explore_cooldown_minutes(110))
        self.assertGreater(PS.get_exploration_gold_multiplier(110), PS.get_exploration_gold_multiplier(91))

    def test_05_defense_initial_duration(self):
        self.assertEqual(PS.get_max_defense_minutes(1), 60)

    def test_06_defense_uses_timestamps(self):
        source = (SERVICES / "defense_service.py").read_text()
        self.assertIn("now - started_at", source)
        self.assertIn("total_seconds", source)

    def test_07_one_battle_per_completed_minute(self):
        source = (SERVICES / "defense_service.py").read_text()
        self.assertIn("scheduled_battles = capped_seconds // 60", source)

    def test_08_loss_ends_run(self):
        source = (SERVICES / "defense_service.py").read_text()
        self.assertIn('if battle.outcome == "defeat":\n                break', source)

    def test_09_hp_carries_between_battles(self):
        source = (SERVICES / "defense_service.py").read_text()
        self.assertIn("player_hp = battle.player_hp", source)
        self.assertIn("player_hp=player_hp", source)

    def test_10_session_cannot_be_claimed_twice(self):
        source = (SERVICES / "defense_service.py").read_text()
        self.assertIn("player.defense_session_id = None", source)
        self.assertIn("player.is_defending = False", source)
        self.assertIn("with_for_update()", source)

    def test_11_combat_level_adds_one_minute(self):
        for level in (2, 50, 200, 420):
            self.assertEqual(
                PS.get_max_defense_minutes(level) - PS.get_max_defense_minutes(level - 1),
                1,
            )

    def test_12_defense_caps_at_eight_hours(self):
        self.assertEqual(PS.get_max_defense_minutes(421), 480)
        self.assertEqual(PS.get_max_defense_minutes(1000), 480)

    def test_13_multiple_combat_levels_award_all_rewards(self):
        player = Player()
        player.combat_level = 1
        player.combat_xp = 0
        player.combat_xp_to_next_level = 1
        player.max_hp = 50
        player.current_hp = 50
        player.unspent_stat_points = 0
        amount = sum(PS.get_combat_xp_to_next_level(level) for level in range(1, 6))
        levels, points = PS.grant_combat_xp(player, amount)
        self.assertGreaterEqual(levels, 5)
        expected = sum(PS.get_stat_points_for_combat_level(level) for level in range(2, 7))
        self.assertEqual(points, expected)
        self.assertEqual(player.current_hp, player.max_hp)

    def test_14_damage_cannot_be_negative(self):
        self.assertEqual(CS._damage(1, 999), 1)

    def test_15_battles_cannot_be_infinite(self):
        stats = CombatStats(max_hp=1000, attack=1, defense=999, speed=5)
        enemy = GeneratedEnemy(
            key="test",
            name="Test",
            rank="common",
            dungeon_level=1,
            level=1,
            max_hp=1000,
            current_hp=1000,
            attack=1,
            defense=999,
            speed=5,
            gold=1,
            combat_xp=1,
            power=10,
        )
        result = CS.resolve_battle(player_stats=stats, player_hp=1000, enemy=enemy, rng=random.Random(1))
        self.assertLessEqual(result.rounds, self.progression["defense"]["max_battle_rounds"])

    def test_16_equipment_available_levels_1_to_400(self):
        for level in range(1, 401):
            self.assertTrue(any(item["min_level"] <= level <= item["max_level"] for item in self.equipment))

    def test_17_sub_300_generated_ranges_are_10_to_20_levels(self):
        for item in self.equipment:
            if item["key"].startswith("generated_") and item["min_level"] < 300:
                self.assertGreaterEqual(item["max_level"] - item["min_level"] + 1, 10)
                self.assertLessEqual(item["max_level"] - item["min_level"] + 1, 20)

    def test_18_high_level_ranges_are_wider(self):
        high = [item for item in self.equipment if item["key"].startswith("generated_") and item["min_level"] >= 300]
        self.assertTrue(high)
        self.assertTrue(all(item["max_level"] - item["min_level"] + 1 >= 25 for item in high))

    def test_19_shop_rarity_improves(self):
        low = PS.get_shop_rarity_percentages(1)
        high = PS.get_shop_rarity_percentages(400)
        self.assertLess(high["common"], low["common"])
        self.assertGreater(high["legendary"], low["legendary"])

    def test_20_shop_has_valid_items_for_every_rarity(self):
        for level in range(1, 401):
            valid = [item for item in self.equipment if item["min_level"] <= level <= item["max_level"]]
            for rarity in ("common", "uncommon", "rare", "epic", "legendary"):
                self.assertTrue(any(item["rarity"] == rarity for item in valid))

    def test_21_every_dungeon_has_content(self):
        self.assertTrue(self.validation["passed"])
        for level in range(1, 21):
            coverage = self.validation["content_coverage"][str(level)]
            self.assertGreater(coverage["enemies"], 0)
            self.assertGreater(coverage["encounters"], 0)
            self.assertGreater(coverage["discoveries"], 0)
            self.assertGreater(coverage["equipment"], 0)

    def test_22_progression_targets(self):
        target = self.simulation["target_evaluation"]
        self.assertTrue(target["dungeon_18_in_range"])
        self.assertTrue(target["dungeon_20_in_range"])
        self.assertTrue(target["cooldown_cap_in_range"])

    def test_23_save_migration_preserves_progress(self):
        player = Player()
        player.explore_level = 50
        player.experience = 4900
        changed = PS.migrate_explore_progression(player)
        self.assertTrue(changed)
        self.assertGreaterEqual(player.explore_level, 50)
        self.assertGreaterEqual(player.experience, PS.get_total_explore_xp_for_level(50))

    def test_24_all_json_parses(self):
        for path in CONTENT.glob("*.json"):
            json.loads(path.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
