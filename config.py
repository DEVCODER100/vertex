"""Central settings. Secrets come from .env; gameplay numbers are plain constants you can tweak."""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str) -> int | None:
    """Read an optional integer env var (Discord IDs). Returns None if unset/invalid."""
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else None


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


# ---- secrets / server setup (.env) ---------------------------------------

TOKEN: str = os.getenv("DISCORD_TOKEN", "").strip()

# Your server's ID. When set, slash commands sync to it instantly (great while developing).
GUILD_ID: int | None = _get_int("GUILD_ID")

# Channel where greetings are posted. Falls back to the server's system channel if unset.
WELCOME_CHANNEL_ID: int | None = _get_int("WELCOME_CHANNEL_ID")

# Channel for automatic quiz drops. Leave unset to keep automatic drops OFF.
QUIZ_CHANNEL_ID: int | None = _get_int("QUIZ_CHANNEL_ID")

# Post a short goodbye when someone leaves.
SEND_GOODBYE: bool = _get_bool("SEND_GOODBYE", default=False)

# ---- bot behaviour --------------------------------------------------------

PREFIX = ","
DB_PATH = os.getenv("DB_PATH", "data/vertex.db").strip() or "data/vertex.db"

# Currencies
CURRENCY_NAME = "Vertex Coins"
CURRENCY_EMOJI = "🪙"
CREDITS_NAME = "Credits"
CREDITS_EMOJI = "💎"

# XP: awarded per message, at most once per cooldown
XP_MIN = 15
XP_MAX = 25
XP_COOLDOWN_SECONDS = 60

# Daily reward
DAILY_AMOUNT = 500
DAILY_COOLDOWN_SECONDS = 24 * 60 * 60

# Premium roles bought with Credits. `,setuptiers` creates these roles and adds them to the shop.
# (name, price in Credits, role colour)
TIER_ROLES = [
    ("Elite", 10_000, 0x9DB4C0),
    ("Divine", 30_000, 0xF5C542),
    ("Mythic", 45_000, 0x9B59F6),
    ("Void", 60_000, 0x3A3F8F),
    ("Eternal", 80_000, 0xFF5FA2),
]

# Staff roles made by `,createroles`, highest rank first: (name, colour).
# They're created WITHOUT any permissions: set those yourself in Server Settings -> Roles.
SERVER_ROLES = [
    ("Owner", 0xE74C3C),
    ("Co-Owner", 0xE67E22),
    ("Manager", 0xF1C40F),
    ("Senior Moderator", 0x2ECC71),
    ("Moderator", 0x1ABC9C),
    ("Junior Moderator", 0x3498DB),
    ("Trial Moderator", 0x9B59B6),
]

# Level badge roles: (level, name, emoji, colour). Badges are permanent: once earned they stay,
# and they are kept when a member prestiges. `,setupbadges` creates these and the Prestige roles.
LEVEL_BADGES = [
    (0, "Level 0", "🦑", 0x7F8C8D),
    (5, "Level 5", "🧠", 0x8FA3AD),
    (10, "Level 10", "🌂", 0x57F287),
    (20, "Level 20", "🎈", 0x1ABC9C),
    (30, "Level 30", "🐬", 0x3498DB),
    (40, "Level 40", "🐠", 0x5865F2),
    (50, "Level 50", "🐉", 0x9B59B6),
    (60, "Level 60", "🔮", 0xE91E63),
    (70, "Level 70", "🌵", 0xE67E22),
    (80, "Level 80", "🌻", 0xF1C40F),
    (90, "Level 90", "🌙", 0xF39C12),
    (100, "Level 100", "🔱", 0xFFD700),
]

# Prestige: at MAX_LEVEL a member can run `,prestige` to drop back to PRESTIGE_START_LEVEL and
# earn the next Prestige role, up to MAX_PRESTIGE. (prestige, name, emoji, colour)
PRESTIGE_ROLES = [
    (1, "Prestige 1", "⭐", 0x57F287),
    (2, "Prestige 2", "🌟", 0xF1C40F),
    (3, "Prestige 3", "✨", 0x3498DB),
    (4, "Prestige 4", "💫", 0x9B59B6),
    (5, "Prestige 5", "🌠", 0xEB459E),
    (6, "Prestige 6", "🔥", 0xE67E22),
    (7, "Prestige 7", "⚡", 0x1ABC9C),
    (8, "Prestige 8", "💎", 0xE91E63),
    (9, "Prestige 9", "👑", 0xECF0F1),
    (10, "Prestige 10", "🏆", 0xE74C3C),
]
MAX_LEVEL = 100
MAX_PRESTIGE = 10
PRESTIGE_START_LEVEL = 1
# True: members keep every level badge they've passed (Level 5 + Level 10 + Level 20 ...).
# False: they keep only their highest one (Level 10 replaces Level 5).
# Prestige roles always show only the current prestige. Prestiging resets level badges.
STACK_LEVEL_ROLES = True
# Same idea for prestige: True keeps Prestige 1, 2, 3 ... as you climb; False shows only the current one.
STACK_PRESTIGE_ROLES = True

# Level-gated media: members below these levels can't post GIFs / pictures (staff are exempt).
# Anyone who has prestiged counts as max level.
GIF_MIN_LEVEL = 10
IMAGE_MIN_LEVEL = 20

# Quiz drops
QUIZ_MIN_MINUTES = 20              # a new question every 20-40 minutes...
QUIZ_MAX_MINUTES = 40
QUIZ_ACTIVE_WINDOW_MINUTES = 10    # ...but only while chat is active:
QUIZ_ACTIVE_MIN_MESSAGES = 3       # at least this many human messages in the window
QUIZ_ANSWER_SECONDS = 30
QUIZ_KIND_WEIGHTS = {"flag": 1, "math": 1, "trivia": 1}
# Each correct answer wins ONE random reward (coins or Credits) plus guaranteed XP.
QUIZ_COINS_RANGE = (1_000, 30_000)
QUIZ_CREDITS_RANGE = (1_000, 3_000)
QUIZ_CREDITS_CHANCE = 0.25         # chance that the reward is Credits instead of coins
QUIZ_XP_RANGE = (40, 100)

# Gambling (payout odds live in games.py)
MIN_BET = 10
GAMBLING_COOLDOWN_SECONDS = 3

# Social
MAX_CHILDREN = 10
PROPOSAL_TIMEOUT_SECONDS = 60
GIF_API_URL = "https://api.otakugifs.xyz/gif"
CUSTOM_GIFS_PATH = "data/gifs.json"  # optional: {"kill": ["https://...gif", ...]} overrides the API

# Custom roles: owning a tier role (Elite ... Eternal) lets you create your own role (free).
# Each tier can share it with this many friends. Highest tier you own counts.
TIER_FRIEND_LIMITS = {"Elite": 0, "Divine": 8, "Mythic": 12, "Void": 16, "Eternal": 28}
