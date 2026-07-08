from bot.services.discord_emoji_service import DiscordEmojiService
from bot.services.equipment_service import EquipmentItem
from bot.utils.emoji import influence_emoji, gold_emoji


ZERO_WIDTH_SPACE = "\u200b"   # invisible spacer for vertical spacing
NBSP = "\u00A0"               # non-breaking space
EM_SPACE = "\u2003"           # wider visible space
EN_SPACE = "\u2002"           # medium visible space

def influence_value(hero_influence: int, villain_influence: int, emoji_service: DiscordEmojiService) -> str:
    ''' Display influence values with good and evil emojis. '''
    return f"{influence_emoji("good")} {hero_influence} : {villain_influence} {influence_emoji("evil")}"

def format_gold(amount: int) -> str:
    return f"{gold_emoji()} {amount}"

def format_item_stats(item: EquipmentItem) -> str:
    return f"HP {item.hp} | ATK {item.attack} | DEF {item.defense} | SPD {item.speed}"