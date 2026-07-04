from __future__ import annotations

import logging

import discord
from sqlalchemy.orm import sessionmaker

from bot.services.encounter_service import Encounter
from bot.services.exploration_service import (
    ExplorationAlreadyResolvedError,
    ExplorationExpiredError,
    ExplorationNotOwnedError,
    ExplorationService,
)
from bot.utils.embeds import WARM_GOLD, embed
from bot.utils.time import human_duration

log = logging.getLogger(__name__)


class ExplorationView(discord.ui.View):
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        exploration_service: ExplorationService,
        resolution_key: str,
        owner_user_id: int,
        encounter: Encounter,
    ) -> None:
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.exploration_service = exploration_service
        self.resolution_key = resolution_key
        self.owner_user_id = owner_user_id
        for choice in encounter.choices:
            self.add_item(ExplorationButton(choice.key, choice.label))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "This expedition belongs to another player.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def resolve_choice(self, interaction: discord.Interaction, choice_key: str) -> None:
        await interaction.response.defer()
        try:
            with self.session_factory() as db:
                result = self.exploration_service.resolve(
                    db,
                    resolution_key=self.resolution_key,
                    choice_key=choice_key,
                    acting_user_id=interaction.user.id,
                )
                db.commit()
        except ExplorationNotOwnedError:
            await interaction.followup.send("This expedition belongs to another player.", ephemeral=True)
            return
        except ExplorationExpiredError:
            await interaction.followup.send("That expedition has expired.", ephemeral=True)
            return
        except ExplorationAlreadyResolvedError:
            await interaction.followup.send("That expedition has already been resolved.", ephemeral=True)
            return
        except Exception:
            log.exception("Failed to resolve exploration")
            await interaction.followup.send("The dungeon coughed up the magic blue smoke. Something is wrong with the dungeon. Please try again.", ephemeral=True)
            return

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        result_embed = embed(result.encounter.title, result.choice.result_text, colour=WARM_GOLD)
        result_embed.add_field(name="Rewards", value=f"{result.gold} gold\n{result.experience} XP")
        result_embed.add_field(name="Energy", value=f"{result.energy_state.energy}/12 remaining")
        if result.discovery_name:
            label = "New Discovery" if result.new_discovery else "Discovery Revisited"
            result_embed.add_field(name=label, value=result.discovery_name, inline=False)
        if result.leveled_up:
            result_embed.add_field(name="Level Up", value="Your dungeon title grows heavier.", inline=False)
        if result.energy_state.next_energy_at:
            result_embed.add_field(
                name="Next Energy",
                value=human_duration(result.energy_state.seconds_until_next),
            )
        await interaction.edit_original_response(embed=result_embed, view=self)


class ExplorationButton(discord.ui.Button):
    def __init__(self, choice_key: str, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"explore:{choice_key}")
        self.choice_key = choice_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ExplorationView):
            await interaction.response.send_message("This expedition is no longer available.", ephemeral=True)
            return
        await view.resolve_choice(interaction, self.choice_key)

