from __future__ import annotations

import discord

DEEP_NAVY = 0x0E1F33
MIDNIGHT_BLUE = 0x1C2E4A
ROYAL_BLUE = 0x3E5FA8
WARM_GOLD = 0xD4AF37
FOOTER = "Kellrond Games: Dungeon Steward"


def embed(title: str, description: str | None = None, *, colour: int = ROYAL_BLUE) -> discord.Embed:
    result = discord.Embed(title=title, description=description, colour=colour)
    result.set_footer(text=FOOTER)
    return result

