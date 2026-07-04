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


def test_administrator_style_permission_is_accepted():
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

