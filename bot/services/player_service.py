from __future__ import annotations
from typing import Callable
from dataclasses import dataclass


from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.config import MAX_ENERGY, PROGRESSION_SCHEMA_VERSION
from bot.models import GuildDungeon, Player
from bot.services import progression_content
from bot.services.progression_service import migrate_explore_progression
from bot.utils.time import utc_now


class PlayerService:
    def get_or_create(
        self, session: Session, *, guild_id: int, user_id: int, display_name: str
    ) -> Player:
        player = session.scalar(
            select(Player).where(Player.guild_id == guild_id, Player.discord_user_id == user_id)
        )
        if player is None:
            content = progression_content.PROGRESSION_CONTENT
            player = Player(
                guild_id=guild_id,
                discord_user_id=user_id,
                display_name=display_name[:120],
                energy=MAX_ENERGY,
                energy_updated_at=utc_now(),
                combat_xp_to_next_level=int(content.combat_leveling.xp_to_next_level.base),
                current_hp=content.new_player.base_hp,
                max_hp=content.new_player.base_hp,
                attack=content.new_player.attack,
                defense=content.new_player.defense,
                speed=content.new_player.speed,
                progression_schema_version=content.schema_version,
            )
            session.add(player)
            session.flush()
        else:
            player.display_name = display_name[:120]
        migrate_explore_progression(player)
        player.highest_unlocked_dungeon_level = max(1, int(player.highest_unlocked_dungeon_level or 1))
        player.highest_completed_dungeon_level = max(1, int(player.highest_completed_dungeon_level or 1))
        player.defense_wins = max(0, int(player.defense_wins or 0))
        player.progression_schema_version = max(
            int(player.progression_schema_version or 0),
            PROGRESSION_SCHEMA_VERSION,
        )
        return player

    def get_or_create_guild(self, session: Session, *, guild_id: int) -> GuildDungeon:
        dungeon = session.scalar(select(GuildDungeon).where(GuildDungeon.discord_guild_id == guild_id))
        if dungeon is None:
            dungeon = GuildDungeon(discord_guild_id=guild_id)
            session.add(dungeon)
            session.flush()
        return dungeon


def title_for_player(player: Player) -> str:
    if player.explore_level >= 10 or player.total_explorations >= 100:
        return "Apprentice Dungeon Master"
    if player.discoveries_found >= 20:
        return "Dungeon Steward"
    if player.gold >= 500:
        return "Keeper of Keys"
    if player.total_explorations >= 25:
        return "Goblin Supervisor"
    if player.total_explorations >= 5:
        return "Corridor Scout"
    return "Dungeon Visitor"



# dataclass handles creating the __init__, __repr__, and other methods automatically.
#  frozen=True parameter makes the instances immutable
#  slots=True optimizes memory usage by preventing the creation of a __dict__ 
#             for each instance.
@dataclass(frozen=True, slots=True)
class TitleRule:
    name: str
    category: str
    priority: int
    condition: Callable[[Player], bool]


DEFAULT_TITLE = "Dungeon Visitor"


def _success_rate(player: Player) -> float:
    if player.total_explorations <= 0:
        return 0.0
    return player.successful_explorations / player.total_explorations


def _failure_rate(player: Player) -> float:
    if player.total_explorations <= 0:
        return 0.0
    return player.failed_explorations / player.total_explorations


def _stat_spread(player: Player) -> int:
    values = (player.attack, player.defense, player.speed)
    return max(values) - min(values)


TITLE_RULES: tuple[TitleRule, ...] = (
    # Exploration count: 8 titles
    TitleRule("Corridor Scout", "exploration", 20, lambda p: p.total_explorations >= 5),
    TitleRule("Passage Prowler", "exploration", 35, lambda p: p.total_explorations >= 15),
    TitleRule("Goblin Supervisor", "exploration", 50, lambda p: p.total_explorations >= 25),
    TitleRule("Hallway Surveyor", "exploration", 75, lambda p: p.total_explorations >= 50),
    TitleRule("Mapper of Moving Halls", "exploration", 110, lambda p: p.total_explorations >= 100),
    TitleRule("Delver of Dusty Depths", "exploration", 165, lambda p: p.total_explorations >= 250),
    TitleRule("Lantern of the Labyrinth", "exploration", 230, lambda p: p.total_explorations >= 500),
    TitleRule("Walker of Endless Corridors", "exploration", 320, lambda p: p.total_explorations >= 1_000),

    # Explore level: 6 titles
    TitleRule("Cellar Apprentice", "explore_level", 30, lambda p: p.explore_level >= 3),
    TitleRule("Tunnel Initiate", "explore_level", 55, lambda p: p.explore_level >= 5),
    TitleRule("Apprentice Dungeon Master", "explore_level", 125, lambda p: p.explore_level >= 10),
    TitleRule("Adept of Hidden Ways", "explore_level", 205, lambda p: p.explore_level >= 20),
    TitleRule("Grand Delver", "explore_level", 300, lambda p: p.explore_level >= 35),
    TitleRule("Sovereign of the Labyrinth", "explore_level", 430, lambda p: p.explore_level >= 50),

    # Exploration outcomes: 7 titles
    TitleRule("Lucky Forager", "exploration_outcome", 45, lambda p: p.successful_explorations >= 10),
    TitleRule("Reliable Delver", "exploration_outcome", 135, lambda p: p.successful_explorations >= 100),
    TitleRule("Unerring Pathfinder", "exploration_outcome", 275, lambda p: p.successful_explorations >= 500),
    TitleRule("Trap Tester", "exploration_outcome", 40, lambda p: p.failed_explorations >= 10),
    TitleRule("Mimic's Favourite Customer", "exploration_outcome", 115, lambda p: p.failed_explorations >= 50),
    TitleRule(
        "Master of Safe Passage",
        "exploration_outcome",
        340,
        lambda p: p.total_explorations >= 250 and _success_rate(p) >= 0.90,
    ),
    TitleRule(
        "Patron Saint of Pitfalls",
        "exploration_outcome",
        215,
        lambda p: p.total_explorations >= 100 and _failure_rate(p) >= 0.50,
    ),

    # Discoveries: 6 titles
    TitleRule("Curious Custodian", "discoveries", 25, lambda p: p.discoveries_found >= 1),
    TitleRule("Relic Finder", "discoveries", 65, lambda p: p.discoveries_found >= 5),
    TitleRule("Secret Seeker", "discoveries", 105, lambda p: p.discoveries_found >= 10),
    TitleRule("Dungeon Steward", "discoveries", 175, lambda p: p.discoveries_found >= 20),
    TitleRule("Curator of Forgotten Things", "discoveries", 290, lambda p: p.discoveries_found >= 50),
    TitleRule("Loremaster Beneath the Stone", "discoveries", 410, lambda p: p.discoveries_found >= 100),

    # Gold: 7 titles
    TitleRule("Copper Counter", "gold", 15, lambda p: p.gold >= 100),
    TitleRule("Keeper of Keys", "gold", 60, lambda p: p.gold >= 500),
    TitleRule("Purse of Plenty", "gold", 100, lambda p: p.gold >= 2_500),
    TitleRule("Dungeon Treasurer", "gold", 180, lambda p: p.gold >= 10_000),
    TitleRule("Master of Coin and Cobweb", "gold", 260, lambda p: p.gold >= 50_000),
    TitleRule("Hoard Warden", "gold", 365, lambda p: p.gold >= 250_000),
    TitleRule("Lord of the Bottomless Vault", "gold", 485, lambda p: p.gold >= 1_000_000),

    # General experience: 4 titles
    TitleRule("Freshly Educated Menace", "experience", 70, lambda p: p.experience >= 1_000),
    TitleRule("Seasoned Steward", "experience", 155, lambda p: p.experience >= 10_000),
    TitleRule("Scholar of Stone and Shadow", "experience", 285, lambda p: p.experience >= 100_000),
    TitleRule("Ancient Hand of the Dungeon", "experience", 455, lambda p: p.experience >= 1_000_000),

    # Combat level: 6 titles
    TitleRule("Cellar Brawler", "combat_level", 32, lambda p: p.combat_level >= 3),
    TitleRule("Goblin Bruiser", "combat_level", 58, lambda p: p.combat_level >= 5),
    TitleRule("Hall Defender", "combat_level", 130, lambda p: p.combat_level >= 10),
    TitleRule("Dungeon Champion", "combat_level", 220, lambda p: p.combat_level >= 20),
    TitleRule("Warlord Below", "combat_level", 315, lambda p: p.combat_level >= 35),
    TitleRule("Dread Castellan", "combat_level", 445, lambda p: p.combat_level >= 50),

    # Defense wins: 7 titles
    TitleRule("First Blood", "defense_wins", 18, lambda p: p.defense_wins >= 1),
    TitleRule("Doorway Defender", "defense_wins", 68, lambda p: p.defense_wins >= 10),
    TitleRule("Hero Handler", "defense_wins", 145, lambda p: p.defense_wins >= 50),
    TitleRule("Breaker of Sieges", "defense_wins", 235, lambda p: p.defense_wins >= 100),
    TitleRule("Bane of Adventurers", "defense_wins", 330, lambda p: p.defense_wins >= 250),
    TitleRule("Guardian of a Thousand Battles", "defense_wins", 470, lambda p: p.defense_wins >= 1_000),
    TitleRule("The Unbreached", "defense_wins", 610, lambda p: p.defense_wins >= 5_000),

    # Dungeon progression: 8 titles
    TitleRule("Keeper of the Second Floor", "dungeon_progression", 80, lambda p: p.highest_unlocked_dungeon_level >= 2),
    TitleRule("Warden of Five Depths", "dungeon_progression", 160, lambda p: p.highest_completed_dungeon_level >= 5),
    TitleRule("Keybearer of Ten Gates", "dungeon_progression", 270, lambda p: p.highest_unlocked_dungeon_level >= 10),
    TitleRule("Master of Ten Floors", "dungeon_progression", 350, lambda p: p.highest_completed_dungeon_level >= 10),
    TitleRule("Opener of Forbidden Depths", "dungeon_progression", 395, lambda p: p.highest_unlocked_dungeon_level >= 15),
    TitleRule("Lord of Fifteen Descents", "dungeon_progression", 505, lambda p: p.highest_completed_dungeon_level >= 15),
    TitleRule("The Dungeon Unbound", "dungeon_progression", 570, lambda p: p.highest_unlocked_dungeon_level >= 20),
    TitleRule("Conqueror of the Twentieth Depth", "dungeon_progression", 690, lambda p: p.highest_completed_dungeon_level >= 20),

    # Hero influence: 6 titles
    TitleRule("Hero's Acquaintance", "hero_influence", 42, lambda p: p.hero_influence >= 10),
    TitleRule("Friend of Foolhardy Adventurers", "hero_influence", 120, lambda p: p.hero_influence >= 50),
    TitleRule("Lantern of Virtue", "hero_influence", 210, lambda p: p.hero_influence >= 150),
    TitleRule("Champion of the Bright Path", "hero_influence", 310, lambda p: p.hero_influence >= 500),
    TitleRule("Paragon Beneath the Mountain", "hero_influence", 440, lambda p: p.hero_influence >= 1_500),
    TitleRule("Beacon of the Deep", "hero_influence", 585, lambda p: p.hero_influence >= 5_000),

    # Villain influence: 6 titles
    TitleRule("Accomplice in the Dark", "villain_influence", 43, lambda p: p.villain_influence >= 10),
    TitleRule("Goblin's Trusted Associate", "villain_influence", 122, lambda p: p.villain_influence >= 50),
    TitleRule("Whisperer of Wicked Plans", "villain_influence", 212, lambda p: p.villain_influence >= 150),
    TitleRule("Architect of Misfortune", "villain_influence", 312, lambda p: p.villain_influence >= 500),
    TitleRule("Dread Patron of the Deep", "villain_influence", 442, lambda p: p.villain_influence >= 1_500),
    TitleRule("Shadow Behind the Throne", "villain_influence", 587, lambda p: p.villain_influence >= 5_000),

    # Good/evil balance: 5 titles
    TitleRule(
        "Keeper of the Scales",
        "balance",
        190,
        lambda p: p.hero_influence + p.villain_influence >= 100
        and abs(p.hero_influence - p.villain_influence) <= 10,
    ),
    TitleRule(
        "Mediator of Monsters and Men",
        "balance",
        325,
        lambda p: p.hero_influence >= 250
        and p.villain_influence >= 250
        and abs(p.hero_influence - p.villain_influence) <= 50,
    ),
    TitleRule(
        "Master of Necessary Evils",
        "balance",
        460,
        lambda p: p.hero_influence >= 750 and p.villain_influence >= 750,
    ),
    TitleRule(
        "Hand Between Light and Shadow",
        "balance",
        555,
        lambda p: p.hero_influence >= 2_000
        and p.villain_influence >= 2_000
        and abs(p.hero_influence - p.villain_influence) <= 200,
    ),
    TitleRule(
        "True Dungeon Master",
        "balance",
        680,
        lambda p: p.hero_influence >= 5_000
        and p.villain_influence >= 5_000
        and abs(p.hero_influence - p.villain_influence) <= 500,
    ),

    # Individual stats: 12 titles
    TitleRule("Iron Fist", "attack", 90, lambda p: p.attack >= 20),
    TitleRule("Dungeon Reaver", "attack", 245, lambda p: p.attack >= 50),
    TitleRule("Living Siege Engine", "attack", 420, lambda p: p.attack >= 100),
    TitleRule("Stone Skin", "defense", 92, lambda p: p.defense >= 20),
    TitleRule("The Wall That Walks", "defense", 247, lambda p: p.defense >= 50),
    TitleRule("Adamant Warden", "defense", 422, lambda p: p.defense >= 100),
    TitleRule("Quickstep", "speed", 88, lambda p: p.speed >= 20),
    TitleRule("Shadow in the Corridor", "speed", 243, lambda p: p.speed >= 50),
    TitleRule("Faster Than Fear", "speed", 418, lambda p: p.speed >= 100),
    TitleRule("Blooded Survivor", "max_hp", 95, lambda p: p.max_hp >= 200),
    TitleRule("Heart of the Dungeon", "max_hp", 250, lambda p: p.max_hp >= 500),
    TitleRule("The Unfelling", "max_hp", 425, lambda p: p.max_hp >= 1_000),

    # Character builds: 7 titles
    TitleRule(
        "Balanced Steward",
        "build",
        280,
        lambda p: min(p.attack, p.defense, p.speed) >= 25 and _stat_spread(p) <= 5,
    ),
    TitleRule(
        "Glass-Cannon Castellan",
        "build",
        380,
        lambda p: p.attack >= 75 and p.attack >= p.defense * 2,
    ),
    TitleRule(
        "Iron Turtle",
        "build",
        382,
        lambda p: p.defense >= 75 and p.defense >= p.attack * 2,
    ),
    TitleRule(
        "Swiftblade of the Lower Halls",
        "build",
        390,
        lambda p: p.attack >= 60 and p.speed >= 60,
    ),
    TitleRule(
        "Living Fortress",
        "build",
        475,
        lambda p: p.defense >= 75 and p.max_hp >= 750,
    ),
    TitleRule(
        "Master-at-Arms",
        "build",
        520,
        lambda p: p.attack >= 75 and p.defense >= 75 and p.speed >= 50,
    ),
    TitleRule(
        "Perfected Vessel",
        "build",
        650,
        lambda p: p.attack >= 100 and p.defense >= 100 and p.speed >= 100 and p.max_hp >= 1_000,
    ),

    # Cross-system legendary titles: 4 titles
    TitleRule(
        "Steward of a Thousand Secrets",
        "legendary",
        720,
        lambda p: p.total_explorations >= 1_000
        and p.discoveries_found >= 100
        and p.explore_level >= 40,
    ),
    TitleRule(
        "Lord of Coin and Conflict",
        "legendary",
        740,
        lambda p: p.gold >= 1_000_000
        and p.combat_level >= 40
        and p.defense_wins >= 1_000,
    ),
    TitleRule(
        "Master of the Twenty Depths",
        "legendary",
        780,
        lambda p: p.highest_completed_dungeon_level >= 20
        and p.defense_wins >= 2_500
        and p.discoveries_found >= 100,
    ),
    TitleRule(
        "Eternal Dungeon Master",
        "legendary",
        900,
        lambda p: p.explore_level >= 50
        and p.combat_level >= 50
        and p.highest_completed_dungeon_level >= 20
        and p.discoveries_found >= 250
        and p.hero_influence >= 2_500
        and p.villain_influence >= 2_500,
    ),
)


def unlocked_titles_for_player(player: Player) -> list[str]:
    """Return every unlocked title from strongest to weakest."""
    unlocked = [rule for rule in TITLE_RULES if rule.condition(player)]
    unlocked.sort(key=lambda rule: rule.priority, reverse=True)
    return [rule.name for rule in unlocked] + [DEFAULT_TITLE]


def title_for_player(player: Player) -> str:
    """Return the highest-priority title currently earned by the player."""
    best_rule = max(
        (rule for rule in TITLE_RULES if rule.condition(player)),
        key=lambda rule: rule.priority,
        default=None,
    )
    return best_rule.name if best_rule is not None else DEFAULT_TITLE






