# Dungeon Steward Progression and Balance Implementation Report

## Executive result

The implemented balance model meets all three primary timing targets in the 15-run typical-player simulation:

- Dungeon 18 median unlock: **day 363**.
- Dungeon 20 median unlock: **day 513**.
- Explore regeneration reaches the 30-minute floor: **day 364**.
- Combat level 400 median: **day 440**.
- Eight-hour defense cap at combat level 421: **day 456**.

The content validator passed with no errors, all 24 acceptance tests passed, and all Python files compile successfully.

## 1. Progression Design

### Separate progression systems

The implementation keeps four independent progression tracks:

1. **Dungeon level** is a selected difficulty and unlock track from 1–20. Previously unlocked levels remain selectable.
2. **Explore level** is derived from cumulative exploration XP and controls energy regeneration plus controlled reward growth.
3. **Combat level** is earned through successful passive-defense battles and grants HP, stat points, and defense-duration growth.
4. **Equipment/shop level** controls item availability and shop rarity without reusing either player level.

### Explore XP and energy

Explore level 1 is the starting level. XP required for the next level uses a bounded quadratic curve:

```text
n = exploreLevel - 1
xpToNext = round(72 + 10.5n + 0.58n²)
```

Energy regeneration is timestamp-driven and uses:

```text
cooldownMinutes = max(30, 120 - (exploreLevel - 1))
```

The 30-minute floor is therefore reached at explore level 91. Explore levels continue after level 91. Post-cap levels do not reduce cooldown further; they add **0.4% exploration gold per level**, subject to the configured reward controls.

Existing saves are migrated conservatively: stored XP is never reduced, and a stored explore level is converted to at least the cumulative XP needed for that level under the new curve.

### Exploration rewards

Exploration gold and XP now account for:

- Explore level.
- Selected dungeon level.
- Encounter rarity.
- Success/failure and risk.
- Player power compared with the dungeon's expected power.

Dungeon gold grows by 8% of the level offset and dungeon XP by 2.2% of the level offset before additional modifiers. Underpowered players still receive rewards, but the multiplier floors at 55%, preventing the highest unlocked dungeon from always being the best farm. Failed choices receive 78% XP, while risky successful gold choices can receive an 18% bonus.

### Dungeon unlocks

Each dungeon after level 1 requires a combination of:

- Explore level.
- Combat level.
- Equipment power.
- Discovery count.
- Successful defense wins.
- Completion of the preceding dungeon.

`dungeon_progression_service.py` evaluates unlock state and exposes all unmet requirements. Entry checks permit any dungeon from level 1 through the player's highest unlocked level, preventing permanent lock-in to unsuitable content.

### Combat XP, HP, stats, and duration

Combat XP uses a controlled quadratic curve:

```text
n = combatLevel - 1
xpToNext = clamp(round(1140 + 169n + 0.23n²), 1140, 250000)
```

Combat XP is scaled by enemy power relative to player power. Trivial enemies receive a severe XP reduction, while near-tier and stronger enemies receive better rewards within configured floors and ceilings.

Base HP is 50. Per-level HP gain starts at 2, grows slowly, and caps at 7. Every 25 combat levels adds a further 5 HP milestone bonus. Stat points begin at 1 per level, slowly reach 2, and receive an extra point every 20 levels.

Defense duration is literal one-minute-per-combat-level growth:

```text
maxDefenseMinutes = min(480, 60 + combatLevel - 1)
```

A defense session starts at full effective HP, resolves one complete battle per completed minute, carries HP between battles, and ends immediately on the first loss. Session IDs and state clearing prevent double claims. Timestamp validation handles future/corrupt values, negative elapsed time, and excessive offline intervals.

### Combat resolution and enemies

Battles use weighted speed initiative, alternating attacks, configurable minimum damage of 1, and a maximum of 100 rounds. Player and enemy statistics are validated before combat. Randomness can use a seeded `random.Random` instance for reproducible tests.

Enemy definitions now include rank classification (`common`, `standard`, `dangerous`, `elite`, or `boss`). Enemy level contributes 3.5% stat growth and 4% reward growth per level offset. Dungeon and enemy-stage modifiers remain multiplicative. Combat gold is globally constrained and receives an additional reduction when enemies are far below player power, correcting low-risk defense farming.

### Equipment scaling and shop rarity

A deterministic generator with seed `20260703` creates continuous equipment coverage. Generated items use level, rarity, slot profile, and controlled variance to determine total stat budget and price. Rarity and level remain reliable indicators of expected power, while slot identity controls how that budget is distributed.

Normal generated ranges below level 300 span 15 levels. Endgame ranges widen to 35–75 levels to avoid excessive content volume while retaining coverage. Item descriptions are stored in a sidecar file so the original equipment schema remains compatible.

Shop rarity changes by configurable level bands:

| Shop level | Common % | Uncommon % | Rare % | Epic % | Legendary % |
|---|---|---|---|---|---|
| 1 | 68.0 | 24.0 | 6.0 | 1.0 | 1.0 |
| 25 | 58.0 | 28.0 | 10.0 | 3.0 | 1.0 |
| 50 | 48.0 | 30.0 | 15.0 | 5.0 | 2.0 |
| 100 | 38.0 | 31.0 | 20.0 | 8.0 | 3.0 |
| 200 | 27.0 | 31.0 | 25.0 | 12.0 | 5.0 |
| 300 | 20.0 | 28.0 | 28.0 | 17.0 | 7.0 |
| 400 | 15.0 | 24.0 | 30.0 | 21.0 | 10.0 |

The shop selector builds its rarity weights only from currently valid items, avoids duplicate keys in one refresh, balances slots where possible, and falls back to the nearest valid level pool rather than returning an empty slot.

## 2. Timeline

### Median dungeon unlock day

| Dungeon | Typical | Casual | Dedicated |
|---|---|---|---|
| 1 | 1 | 1 | 1 |
| 2 | 3 | 4 | 2 |
| 3 | 5 | 10 | 6 |
| 4 | 10 | 19 | 8 |
| 5 | 16 | 27 | 12 |
| 6 | 24 | 43 | 20 |
| 7 | 41 | 73 | 34 |
| 8 | 64 | 112 | 52 |
| 9 | 95 | 170 | 78 |
| 10 | 133 | 236 | 109 |
| 11 | 177 | 313 | 144 |
| 12 | 218 | 386 | 178 |
| 13 | 254 | 451 | 207 |
| 14 | 284 | 505 | 232 |
| 15 | 308 | 548 | 251 |
| 16 | 330 | 588 | 270 |
| 17 | 347 | — | 284 |
| 18 | 363 | — | 297 |
| 19 | 425 | — | 347 |
| 20 | 513 | — | 419 |

The casual profile uses 45% of exploration energy and 0.85 defense sessions per day; it reaches dungeon 16 around day 588 and does not reach dungeon 17 within the 600-day window. The dedicated profile reaches dungeon 20 on day 419, substantially faster than typical but not within only a few months.

### Explore cooldown milestones

Because each explore level removes exactly one minute, the cooldown milestone level is `121 - cooldownMinutes`.

| Cooldown | Explore level | Typical interpretation |
|---|---|---|
| 120 min | 1 | Starting state |
| 105 min | 16 | Early progression |
| 90 min | 31 | Established progression |
| 75 min | 46 | Midgame |
| 60 min | 61 | Long-term midgame |
| 45 min | 76 | Late first year |
| 30 min | 91 | Median day 364 |

### Combat duration milestones

| Combat level | Maximum defense | Typical median day |
|---|---|---|
| 1 | 60 min | 1 |
| 100 | 159 min | 137 |
| 200 | 259 min | 269 |
| 300 | 359 min | 363 |
| 400 | 459 min | 440 |
| 421 | 480 min | 456 |

The typical final progression target is dungeon 20 on median day 513. The model continues beyond this point: by day 600 the typical median is explore level 125 and combat level 578.

## 3. Files Changed

### Modified supplied code

- `progression_content.py` — expanded configurable schemas, upper bounds, dungeon/exploration reward controls, combat milestones, defense safety limits, and rarity bands.
- `progression_service.py` — implemented XP formulas, save migration, cooldown cap behavior, reward formulas, combat-power reward scaling, combat progression, and shop rarity helpers.
- `enemy_service.py` — added expanded dungeon schema validation, enemy ranks, generated enemy power, safer path loading, and full level-coverage validation.
- `combat_service.py` — added combatant validation, power-relative XP/gold, bounded full-battle resolution, and reproducible RNG support.
- `defense_service.py` — added full-HP session starts, timestamp protections, immediate first-loss termination, duplicate-claim protection, and robust state clearing.
- `exploration_service.py` — added dungeon selection persistence/fallback, progression migration, dungeon/risk/rarity/power reward scaling, and compatibility fallback for the existing encounter selector.

### Modified supplied content

- `progression.json` — central source for all tuned formulas and caps.
- `dungeon_levels.json` — added target days, exploration modifiers, expected power, and multi-factor unlock requirements for levels 1–20.
- `enemies.json` — added enemy ranks and rebalanced validation-compatible enemy metadata.
- `equipment.json` — expanded from 49 to 924 items with deterministic level coverage.

### New files

- `dungeon_progression_service.py` — dungeon unlock evaluation and safe re-entry checks.
- `shop_selection.py` — valid-pool-first, duplicate-safe, slot-aware shop selection.
- `generate_equipment.py` — deterministic equipment generation and validation.
- `equipment_descriptions.json` — item descriptions keyed by equipment ID without breaking the original item schema.
- `validate_content.py` — JSON/schema/reference/coverage/equipment/shop validation.
- `content_validation.json` — machine-readable successful validation output.
- `simulate_balance.py` — standalone 600-day casual/typical/dedicated progression simulator.
- `simulation_results.json` — machine-readable results from 45 randomized runs.
- `test_balance_acceptance.py` — automated implementation of all 24 requested acceptance checks.
- `IMPLEMENTATION_REPORT.md` — this report.
- `CODING_AGENT_FOLLOWUP.md` — repo-integration review prompt.

`encounters.json` and `discoveries.json` were not rewritten because their existing 750 encounters and 500 discoveries already provide ample content. They were parsed and validated, including reference and coverage checks.

## 4. Equipment Generation

- Original items: **49**.
- Generated items added: **875**.
- Total items: **924**.
- Deterministic seed: **20260703**.
- Coverage: every shop level from 1 through 400 has at least 35 valid options; generated content continues beyond 400.

### Count by slot

| Slot | Count |
|---|---|
| armor | 132 |
| boots | 132 |
| gloves | 132 |
| helm | 132 |
| shield | 132 |
| trinket | 132 |
| weapon | 132 |

### Count by rarity

| Rarity | Count |
|---|---|
| common | 189 |
| epic | 182 |
| legendary | 189 |
| rare | 182 |
| uncommon | 182 |

Representative valid-pool sizes are 49 items at level 1, 35 at levels 100/200/300, and 56 at level 400. The minimum valid pool anywhere from level 1–400 is 35 and the maximum is 84.

## 5. Economy Results

### Median daily gold by progression stage

| Band | Explore/day | Defense/day | Total/day | Spent/day |
|---|---|---|---|---|
| Days 1–30 | 218.83 | 73.37 | 292.2 | 253.33 |
| Days 31–120 | 380.17 | 300.2 | 680.37 | 636.06 |
| Days 121–365 | 968.98 | 958.36 | 1927.33 | 1869.88 |
| Days 366–600 | 2118.61 | 2942.89 | 5061.5 | 1646.57 |

Across 600 days, the typical median earns **776,963 exploration gold** and **959,923 defense gold**, spends **906,060**, and retains **827,794**. Income is approximately 44.7% exploration and 55.3% defense.

### Representative equipment prices

| Level | Valid items | Median price | Minimum | Maximum | Median legendary |
|---|---|---|---|---|---|
| 1 | 49 | 300 | 45 | 710 | 690 |
| 25 | 56 | 955 | 485 | 2800 | 2200 |
| 50 | 35 | 1480 | 1015 | 2460 | 2450 |
| 100 | 35 | 2655 | 1875 | 4330 | 4280 |
| 200 | 35 | 5690 | 4085 | 8990 | 8925 |
| 300 | 35 | 8415 | 6110 | 13080 | 13030 |
| 400 | 56 | 14128 | 8485 | 18935 | 17430 |

The typical median makes 134 purchases, approximately one every 3.5 days, with a median purchase price of 4,955 gold.

The simulation exposed excessive passive gold from repeatedly defeating weak enemies. This was corrected with a 0.25 combat-gold multiplier plus a 0.35 trivial-enemy multiplier. Exploration also uses an underpowered reward floor rather than granting full highest-tier rewards automatically.

## 6. Tests and Simulations

### Automated tests

`test_balance_acceptance.py` contains 24 tests corresponding to the requested acceptance criteria, including cooldown bounds, post-cap growth, duration math, timestamp resolution, one battle per completed minute, first-loss termination, HP carry-over, duplicate claims, multi-level rewards, finite combat, equipment coverage, rarity improvement, non-empty shops, content coverage, timeline targets, save migration, and JSON/schema validation.

Results:

- **24/24 acceptance tests passed**.
- `validate_content.py`: **passed**, no errors.
- JSON counts: 20 dungeons, 20 enemies, 924 equipment items, 750 encounters, and 500 discoveries.
- Python compilation: all supplied and added `.py` files compiled successfully.

### Simulation

The standalone simulator ran **45 seeded randomized runs**: 15 casual, 15 typical, and 15 dedicated, each for 600 days.

Typical-player results:

- Dungeon 18: day 363 — inside the 330–400 target.
- Dungeon 20: day 513 — inside the 500–600 target.
- Cooldown floor: day 364 — inside the 330–400 target.
- Combat level 400: day 440.
- Eight-hour defense: day 456.
- Equipment power: day 30 `140.68`, day 120 `314.75`, day 240 `559.53`, day 365 `861.01`, day 548 `1186.99`.
- Per-battle death rates generally remain around 0.22–0.34%, which is roughly 290–450 successful battles per loss when a duration cap does not end the session first.

### Assumptions and remaining risks

The supplied subset did not include SQLAlchemy model definitions, database migrations, `EnergyService`, `EncounterService`, the existing equipment/shop service, Discord commands/views, or end-to-end application tests. The implementation therefore uses compatibility fallbacks where practical, but repository integration still needs to verify:

- `EnergyService` calls `get_explore_cooldown_minutes()` rather than duplicating cooldown math.
- Native database columns exist for selected exploration dungeon, highest unlocked/completed dungeon, and durable progression counters.
- `EncounterService.select()` accepts `dungeon_level`; the edited exploration service falls back to the legacy signature until it does.
- The existing shop command delegates selection to `shop_selection.select_shop_items()`.
- Equipment descriptions are loaded from the sidecar file where the UI needs them.
- All incompatible player actions resolve or terminate active defense consistently.

The simulator is a systems-level model, not a replacement for telemetry. Live player behavior, encounter-choice preferences, session interruption patterns, and equipment purchase decisions should be measured after release and used for a later data-driven retune.

## 7. Important Design Decision: Defense Duration Conflict

The four constraints cannot all meet at combat level 400:

- Start at 60 minutes.
- Add exactly one minute per combat level.
- Cap at 480 minutes.
- Reach the cap at level 400.

The implementation preserves the literal one-minute-per-level rule. Level 400 therefore grants:

```text
60 + (400 - 1) = 459 minutes
```

The 480-minute cap is reached at combat level 421:

```text
60 + (421 - 1) = 480 minutes
```

Equipment progression still covers level 400 and beyond. This avoids hidden milestone bonuses or fractional duration gains and makes the rule transparent to players. In the typical simulation, level 400 arrives on day 440 and level 421 on day 456, both within the late-game window.

## 8. Coding-Agent Follow-Up Prompt

The complete ready-to-send prompt is in `CODING_AGENT_FOLLOWUP.md`.
