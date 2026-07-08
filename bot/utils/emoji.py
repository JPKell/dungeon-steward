import discord

from bot.services.discord_emoji_service import DiscordEmojiService
from bot.services.equipment_service import EquipmentItem

emoji_service = DiscordEmojiService()

EMOJI_MAP = {
    "rarity": {
        "common": {
            "custom": "equipment.common",
            "fallback": "⚪"
            },
        "uncommon": {
            "custom": "equipment.uncommon",
            "fallback": "🟢",
            },
        "rare": {
            "custom": "equipment.rare",
            "fallback": "🔵"
            },
        "epic": {
            "custom": "equipment.epic",
            "fallback": "🟣"
            },
        "legendary": {
            "custom": "equipment.legendary",
            "fallback": "🟡"
        }
    },
    "equipment": {
        "weapon": { 
            "axe":      "equipment.weapon_axe",
            "blade":    "equipment.weapon_blade",
            "dirk":     "equipment.weapon_dirk",
            "glaive":   "equipment.weapon_glaive",
            "hammer":   "equipment.weapon_hammer",
            "pike":     "equipment.weapon_pike",
            "saber":    "equipment.weapon_saber",
            "spear":    "equipment.weapon_spear",
            "fallback": "⚔️",
            "empty":    "equipment.weapon_blade",

            },
        "shield": { 
            "aegis":    "equipment.shield_aegis",
            "barrier":  "equipment.shield_barrier",
            "buckler":  "equipment.shield_buckler",
            "bulwark":  "equipment.shield_bulwark",
            "guard":    "equipment.shield_guard",
            "rampart":  "equipment.shield_rampart",
            "ward":     "equipment.shield_ward",
            "fallback": "🛡️",
            "empty":    "equipment.shield_ward",
            },
        "helm": { 
            "coif":      "equipment.helm_coif",
            "crown":     "equipment.helm_crown",
            "greathelm": "equipment.helm_greathelm",
            "helm":      "equipment.helm_helm",
            "hood":      "equipment.helm_hood",
            "mask":      "equipment.helm_mask",
            "visor":     "equipment.helm_visor",
            "fallback":  "🪖",
            "empty":     "equipment.helm_helm",
            },
        "armor": { 
            "carapace": "equipment.armor_carapace",
            "cuirass":  "equipment.armor_cuirass",
            "harness":  "equipment.armor_harness",
            "hauberk":  "equipment.armor_hauberk",
            "mail":     "equipment.armor_mail",
            "plate":    "equipment.armor_plate",
            "vestment": "equipment.armor_vestment",
            "fallback": "🧥",
            "empty":    "equipment.armor_cuirass",
            },
        "gloves": { 
            "bracers":   "equipment.gloves_bracers",
            "claws":     "equipment.gloves_claws",
            "gauntlets": "equipment.gloves_gauntlets",
            "gloves":    "equipment.gloves_gloves",
            "grips":     "equipment.gloves_grips",
            "knuckles":  "equipment.gloves_knuckles",
            "wraps":     "equipment.gloves_wraps",
            "fallback":  "🧤",
            "empty":     "equipment.gloves_gauntlets",
            },
        "boots": { 
            "boots":      "equipment.boots_boots",
            "footguards": "equipment.boots_footguards",
            "greaves":    "equipment.boots_greaves",
            "sabatons":   "equipment.boots_sabatons",
            "sandals":    "equipment.boots_sandals",
            "striders":   "equipment.boots_striders",
            "treads":     "equipment.boots_treads",
            "fallback":   "🥾",
            "empty":      "equipment.boots_greaves",
            },
        "trinket": { 
            "charm":     "equipment.trinket_charm",
            "compass":   "equipment.trinket_compass",
            "idol":      "equipment.trinket_idol",
            "reliquary": "equipment.trinket_reliquary",
            "sigil":     "equipment.trinket_sigil",
            "talisman":  "equipment.trinket_talisman",
            "token":     "equipment.trinket_token",
            "fallback":  "💍",
            "empty":     "equipment.trinket_token",
            }
    },
    "gold": {
        "custom": "misc.gold",
        "fallback": "💰"
    },
    "good": {
        "custom": "misc.good",
        "fallback": "😇"
    },
    "evil": {
        "custom": "misc.evil",
        "fallback": "😈"
    },
    "neutral": {
        "custom": "misc.neutral",
        "fallback": "⚖️"
    },

}

def equipment_emoji(slot: str, item_type: str) -> str:
    """ Returns the emoji for the given equipment slot and type. """
    slot = slot.lower()
    item_type = item_type.lower()
    emoji = EMOJI_MAP.get("equipment", {}).get(slot, {}).get(item_type, "")
    return emoji_service.markdown_for(emoji) or EMOJI_MAP.get("equipment", {}).get(slot, {}).get("fallback", "❓")

def gold_emoji(custom = True) -> str:
    """ Returns the emoji for gold. """
    gold = EMOJI_MAP.get("gold", {})
    if not custom:
        return gold.get("fallback", "💰")
    return emoji_service.markdown_for(gold.get('custom')) or gold.get("fallback", "💰")

def influence_emoji(influence: str) -> str:
    ''' Returns the emoji for the given influence.'''
    influence = influence.lower()
    if influence not in ["good", "evil", "neutral"]:
        return ""
    
    # Fallback to capitalized text if the emoji is not found
    return emoji_service.markdown_for(f"misc.{influence}") or influence.capitalize()

def rarity_badge_emoji(rarity: str, custom: bool = True) -> str:
    """ Returns the emoji for the given rarity. 
        If custom is True, returns the custom emoji if available, 
        otherwise returns the fallback emoji. """
    badge_info = EMOJI_MAP.get("rarity", {}).get(rarity.lower(), {})
    if not custom:
        return badge_info.get("fallback", "⚪")
    return emoji_service.markdown_for(badge_info.get('custom')) or badge_info.get("fallback", "⚪")

