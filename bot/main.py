from __future__ import annotations

import logging

import discord
from discord import app_commands

from bot.commands.admin import DungeonAdminGroup
from bot.commands.dungeon import DungeonGroup
from bot.config import load_settings
from bot.database.session import make_engine, make_session_factory
from bot.logging_config import configure_logging
from bot.services.content_runtime import RuntimeContentError, refresh_runtime_content_from_database

log = logging.getLogger(__name__)


class DungeonStewardBot(discord.Client):
    def __init__(self) -> None:
        self.settings = load_settings()
        configure_logging(self.settings.log_level)
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(intents=intents, application_id=self.settings.discord_application_id)
        self.tree = app_commands.CommandTree(self)
        self.engine = make_engine(self.settings.database_url)
        self.session_factory = make_session_factory(self.engine)
        self._synced = False

    async def setup_hook(self) -> None:
        try:
            refresh_runtime_content_from_database(self.session_factory)
        except Exception as error:
            raise RuntimeContentError(
                "Database content is not loaded. Run `python -m scripts.content_db load` after migrations."
            ) from error
        dungeon_group = DungeonGroup(session_factory=self.session_factory)
        self.tree.add_command(dungeon_group)
        self.tree.add_command(
            DungeonAdminGroup(
                session_factory=self.session_factory,
                settings=self.settings,
                content_reload_callback=dungeon_group.reload_content,
            )
        )
        if self.settings.discord_test_guild_id:
            guild = discord.Object(id=self.settings.discord_test_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synchronized %s commands to test guild %s", len(synced), guild.id)
        elif not self.settings.is_development:
            synced = await self.tree.sync()
            log.info("Synchronized %s global commands", len(synced))
        else:
            log.info("Skipped command sync: set DISCORD_TEST_GUILD_ID for development sync")
        self._synced = True

    async def on_ready(self) -> None:
        log.info("Connected to Discord as %s (%s)", self.user, self.user.id if self.user else "unknown")

    async def on_error(self, event_method: str, /, *args, **kwargs) -> None:
        log.exception("Unexpected Discord error in %s", event_method)


async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    log.exception("Application command failed", exc_info=error)
    message = "Something went sideways in the dungeon. The details have been logged."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def main() -> None:
    bot = DungeonStewardBot()
    bot.tree.on_error = on_app_command_error
    log.info("Starting Dungeon Steward")
    bot.run(bot.settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
