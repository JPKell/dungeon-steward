from __future__ import annotations

import discord


def is_staff(interaction: discord.Interaction, staff_role_id: int | None) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions and permissions.manage_guild:
        return True
    if staff_role_id is None:
        return False
    roles = getattr(interaction.user, "roles", [])
    return any(getattr(role, "id", None) == staff_role_id for role in roles)

