from __future__ import annotations

from dataclasses import dataclass

from bot.services.weekly_objective_service import (
    MIN_DIFFICULTY_INDEX,
    OBJECTIVE_TEMPLATES,
    PARTICIPANT_EXPONENT,
    calculate_reward_preview,
    round_target,
)


@dataclass(frozen=True)
class WeeklyObjectiveSimulationRow:
    template_key: str
    title: str
    participants: int
    difficulty_index: float
    target: int
    reward_gold: int


def simulate_weekly_objectives(
    *,
    participants: tuple[int, ...] = (1, 3, 8, 20),
    difficulty_indexes: tuple[float, ...] = (0.65, 1.0, 1.5, 2.5),
    explore_level: int = 1,
) -> list[WeeklyObjectiveSimulationRow]:
    rows: list[WeeklyObjectiveSimulationRow] = []
    for template in OBJECTIVE_TEMPLATES:
        for participant_count in participants:
            participant_factor = max(1, participant_count) ** PARTICIPANT_EXPONENT
            for difficulty_index in difficulty_indexes:
                raw_target = template.base_target * participant_factor * difficulty_index
                target = round_target(
                    raw_target,
                    metric=template.metric,
                    round_to=template.round_to,
                    minimum=template.base_target * MIN_DIFFICULTY_INDEX,
                )
                reward = calculate_reward_preview(
                    explore_level,
                    effort_tier=template.effort_tier,
                    difficulty_index=difficulty_index,
                )
                rows.append(
                    WeeklyObjectiveSimulationRow(
                        template_key=template.key,
                        title=template.title,
                        participants=participant_count,
                        difficulty_index=difficulty_index,
                        target=target,
                        reward_gold=reward.gold_awarded,
                    )
                )
    return rows


def main() -> None:
    for row in simulate_weekly_objectives():
        print(
            f"{row.template_key},{row.participants},{row.difficulty_index:.2f},"
            f"{row.target},{row.reward_gold}"
        )


if __name__ == "__main__":
    main()
