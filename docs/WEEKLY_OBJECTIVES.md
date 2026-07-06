# Weekly Objectives

Weekly objectives are server-wide goals created by `WeeklyObjectiveService`. Each guild has at most one unresolved objective at a time, protected by the `uq_weekly_guild_active_unresolved` partial index.

## Lifecycle

1. `get_active()` returns the current unresolved objective, resolves expired objectives, or creates the next one.
2. `create_next()` selects one of 50 templates while avoiding the previous 12 template keys, the previous 4 metrics when possible, and more than two repeated modes.
3. Targets scale from the template base target by previous contributors and guild difficulty:

```text
raw_target = base_target * max(1, previous_participants) ** 0.85 * weekly_difficulty_index
```

Gold targets round to 50, XP targets round to 10, and count targets round to whole numbers. The floor is 65% of the template base target.

## Events

Exploration records stable event IDs from the exploration session and only contributes to the active objective's metric:

- `explorations`
- `explore_gold`
- `explore_xp`
- `total_gold`
- `total_xp`
- hero and villain influence gained or reduced
- `stability_gained`
- `discoveries_found`
- `unique_discoveries_found`

Defense records stable event IDs from the defense session:

- `defense_kills`
- `defense_gold`
- `defense_xp`
- `total_gold`
- `total_xp`

`weekly_objective_events` stores idempotency by `(weekly_objective_id, event_id)`. Unique discovery objectives also dedupe by `(weekly_objective_id, metric, unique_key)`.

## Resolution And Rewards

Completing the target succeeds immediately. Expiring below target fails. Success multiplies the guild's next difficulty by `1.10` up to `2.50`; failure multiplies it by `0.85` down to `0.65`.

Successful objectives pay real player gold once per eligible contributor. Eligibility requires at least 1% of the expected individual share:

```text
minimum_required = target / previous_participants * 0.01
```

Rewards are based on the median equipment cost for the player's explore level:

```text
base_reward = max(200, median_equipment_cost * 0.35)
reward = min(max(200, median_equipment_cost * 0.60), base_reward * effort_multiplier * difficulty_multiplier)
difficulty_multiplier = clamp(weekly_difficulty_index ** 0.20, 0.90, 1.20)
```

Reward rows in `weekly_objective_rewards` are the audit trail and idempotency guard.

## Legacy Notes

Older weekly objectives without a v2 metric fall back through `LEGACY_METRIC_MAP`. Previous participant count uses the last resolved weekly objective when available, otherwise recent explorers from the last seven days.
