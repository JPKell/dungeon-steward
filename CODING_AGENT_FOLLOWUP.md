# Coding-Agent Follow-Up Prompt

You are reviewing and integrating a completed Dungeon Steward progression and economy balance pass. Do not replace the tuned progression with arbitrary values. Review the implementation for correctness, integrate it into the full repository, run all tests and simulations, and preserve the verified timing targets unless evidence requires a measured retune.

## Files modified in the balance pass

- `progression_content.py`
- `progression_service.py`
- `enemy_service.py`
- `combat_service.py`
- `defense_service.py`
- `exploration_service.py`
- `progression.json`
- `dungeon_levels.json`
- `enemies.json`
- `equipment.json`

## Files added

- `dungeon_progression_service.py`
- `shop_selection.py`
- `generate_equipment.py`
- `equipment_descriptions.json`
- `validate_content.py`
- `content_validation.json`
- `simulate_balance.py`
- `simulation_results.json`
- `test_balance_acceptance.py`
- `IMPLEMENTATION_REPORT.md`

The supplied `encounters.json` and `discoveries.json` were validated but deliberately not regenerated.

## Implemented architecture

- Explore level starts at 1 and uses a controlled quadratic XP curve.
- Exploration cooldown is `max(30, 120 - (exploreLevel - 1))`, reaching its floor at explore level 91.
- Explore levels continue after the cooldown cap; post-cap levels add gradual gold growth.
- Existing explore saves are migrated without reducing stored XP or level.
- Exploration rewards use explore level, selected dungeon, encounter rarity, success/risk, and player-to-dungeon power ratio.
- Dungeon levels 1–20 have multi-factor unlock requirements: explore level, combat level, equipment power, discoveries, defense wins, and previous-dungeon completion.
- Combat uses full alternating battles, speed-weighted initiative, minimum damage, round caps, HP carry-over, and seeded RNG support.
- Passive defense uses timestamps, one battle per completed minute, full HP at session start, first-loss termination, duplicate-claim prevention, timestamp validation, and a 30-day safety clamp.
- Combat XP and gold are adjusted by enemy/player power to reduce trivial-enemy farming.
- Defense duration follows the literal rule `min(480, 60 + combatLevel - 1)`; level 400 grants 459 minutes and level 421 grants 480 minutes.
- Equipment generation is deterministic with seed `20260703`; 875 items were added for 924 total, with complete shop coverage through level 400 and beyond.
- `shop_selection.py` selects from the valid item pool before applying rarity weights, avoids duplicates, balances slots, and has a nearest-level fallback.
- Configurable shop rarity bands improve item quality from level 1 through 400.
- Standalone validation, acceptance tests, and 600-day balance simulation were added.

## Verified balance results

The current 15-run typical-player median is:

- Dungeon 18: day 363.
- Dungeon 20: day 513.
- Explore cooldown floor: day 364.
- Combat level 400: day 440.
- Combat level 421/eight-hour defense: day 456.

All 24 acceptance tests pass. Content validation passes with 20 dungeons, 20 enemies, 924 items, 750 encounters, and 500 discoveries.

## Required repository review and integration

1. Inspect the real package paths and merge these files into their corresponding `bot/services`, `bot/content`, and test/tool locations. Correct imports without changing behavior.
2. Inspect the SQLAlchemy `Player`, `ExplorationSession`, guild/dungeon, equipment, and history models. Add an Alembic migration or the repository's normal migration for any missing durable fields, including:
   - Selected exploration dungeon level.
   - Highest unlocked dungeon and completed dungeon records, or an equivalent normalized structure.
   - Discovery and defense-win counters used by unlock checks.
   - Defense session fields already referenced by `defense_service.py` if any are missing.
   - A progression schema/version marker if the project has no migration-state mechanism.
3. Integrate `migrate_explore_progression()` into player load/login or a one-time migration. Make it idempotent and add migration tests using legacy saves.
4. Inspect `EnergyService`. It must use timestamp regeneration and call `get_explore_cooldown_minutes(player.explore_level)`. Remove duplicate hard-coded cooldown formulas.
5. Extend `EncounterService.select()` to accept `dungeon_level` and filter/weight encounters appropriately. The edited exploration service currently has a legacy-signature fallback; replace the fallback with the native API after integration.
6. Persist the chosen dungeon level directly on `ExplorationSession`. Remove the resolution-key encoding fallback once the migration is deployed.
7. Wire the dungeon selector into the Discord explore interface and command. Show locked requirements from `get_dungeon_unlock_state()`, allow return to every previously unlocked level, and prevent selection above the highest unlocked level.
8. Define and persist “previous dungeon completed.” Use an explicit completion criterion consistent with the existing game, such as a successful defense threshold, a designated boss victory, or a milestone encounter. Do not substitute “merely entered the dungeon.”
9. Integrate `shop_selection.select_shop_items()` into the real shop refresh flow. Confirm stock size, item ownership rules, slot handling, duplicate prevention, and transaction locking.
10. Load `equipment_descriptions.json` in the equipment/UI layer or migrate descriptions into a schema-supported field. Do not discard the descriptions silently.
11. Verify equipment power calculation against the actual equipped-item model. The simulation assumes a controlled aggregate of HP, attack, defense, speed, rarity, and level.
12. Ensure every incompatible action resolves active defense exactly once before proceeding. This includes exploring, manual stop, starting another defense, and any other activity defined by the full project.
13. Add transaction/concurrency tests for double stop, stop-versus-explore races, expired-session workers, and simultaneous defense starts.
14. Add end-to-end Discord command/view tests for dungeon selection, defense reports, level-up output, shop refresh, purchasing, and returning to lower dungeons.
15. Confirm all config constants are sourced from `progression.json`; remove stale duplicates in `bot.config` only after every call site is migrated.

## Known uncertainties from the supplied subset

- Model definitions and migrations were not supplied.
- `EnergyService`, `EncounterService`, equipment/shop services, and Discord command/UI files were not supplied.
- The exact definition of dungeon completion was unavailable.
- The simulator uses reasonable player-behavior assumptions rather than production telemetry.
- Encounter choice behavior is modeled statistically; it does not reproduce every individual encounter branch.

Resolve these uncertainties against the actual repository rather than inventing incompatible parallel systems.

## Required commands

Run from the integrated project using the correct package/test paths:

```bash
python validate_content.py
python test_balance_acceptance.py
python simulate_balance.py --runs 15 --days 600
python -m compileall bot
pytest
```

Also run the project's formatter, linter, type checker, migration tests, and Discord integration tests.

## Acceptance ranges that must remain true

- Typical dungeon 18 median: day 330–400.
- Typical dungeon 20 median: day 500–600.
- Typical 30-minute explore cooldown: day 330–400.
- Defense never exceeds 480 minutes.
- Dedicated dungeon 20 must not collapse into only a few months.
- Equipment remains available at every shop level 1–400.
- The shop cannot return an empty slot because a selected rarity has no valid item.
- Existing saves cannot lose legitimate XP, levels, currency, equipment, or unlocks.

When changing a formula, threshold, reward, unlock requirement, or equipment generation rule, rerun the simulation with multiple seeds and document the before/after median and outliers. Do not “simplify” the tuned values into flat XP requirements or arbitrary multipliers.
