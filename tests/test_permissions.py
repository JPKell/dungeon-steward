from __future__ import annotations

from types import SimpleNamespace

from bot.commands.permissions import is_staff


def test_staff_role_is_accepted():
    interaction = SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=False),
            roles=[SimpleNamespace(id=42)],
        )
    )
    assert is_staff(interaction, 42) is True


def test_manage_guild_is_rejected_when_staff_role_is_configured():
    interaction = SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=True),
            roles=[],
        )
    )
    assert is_staff(interaction, 42) is False


def test_manage_guild_is_fallback_when_no_staff_role_is_configured():
    interaction = SimpleNamespace(
        user=SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=True), roles=[])
    )
    assert is_staff(interaction, None) is True


def test_ordinary_user_is_rejected():
    interaction = SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=False),
            roles=[SimpleNamespace(id=10)],
        )
    )
    assert is_staff(interaction, 42) is False
