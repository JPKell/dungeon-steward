from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_before_or_equal(left: datetime, right: datetime) -> bool:
    return ensure_utc(left) <= ensure_utc(right)


def human_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds == 0:
        return "now"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts)


def discord_relative_timestamp(when: datetime | None) -> str:
    if when is None:
        return "now"
    return f"<t:{int(ensure_utc(when).timestamp())}:R>"


def add_seconds(when: datetime, seconds: int) -> datetime:
    return ensure_utc(when) + timedelta(seconds=seconds)

