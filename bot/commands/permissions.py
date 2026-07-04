from __future__ import annotations

import discord


def is_staff(interaction: discord.Interaction, staff_role_id: int | None) -> bool:
    if staff_role_id is not None:
        roles = getattr(interaction.user, "roles", [])
        return any(getattr(role, "id", None) == staff_role_id for role in roles)

    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)
