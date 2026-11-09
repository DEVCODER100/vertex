"""Small helpers for finding and ordering roles."""

from __future__ import annotations

import logging
import re

import discord

import config

log = logging.getLogger("vertex.rolesutil")


def norm_name(name: str) -> str:
    """Lowercase letters and digits only, so "📋・rules" and "rules" compare equal."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def match_role(roles, base_name: str):
    """First role called `base_name`, with or without a trailing emoji/label.
    "Level 5" matches "Level 5" and "Level 5 🧠", but never "Level 50"."""
    base = base_name.lower()
    for role in roles:
        name = role.name.lower()
        if name == base or name.startswith(base + " "):
            return role
    return None


def find_role(guild: discord.Guild, base_name: str) -> discord.Role | None:
    return match_role(guild.roles, base_name)


def full_name(name: str, emoji: str) -> str:
    return f"{name} {emoji}".strip()


def upper_rank_names() -> list[str]:
    """Owner > Co-Owner > Manager > Senior Moderator > Moderator > Junior Moderator > Trial Moderator
    > Eternal > Void > Mythic > Divine > Elite."""
    names = [name for name, _color in config.SERVER_ROLES]
    names += [tier[0] for tier in reversed(config.TIER_ROLES)]  # most expensive tier first
    return names


def lower_rank_names() -> list[str]:
    """Prestige 10 ... Prestige 1, then Level 100 ... Level 0."""
    names = [p[1] for p in sorted(config.PRESTIGE_ROLES, reverse=True)]
    names += [b[1] for b in sorted(config.LEVEL_BADGES, reverse=True)]
    return names


def desired_order(below: list) -> list:
    """The order the roles under the bot's top role should have, highest first:
    the staff and tier ranks, then any roles that aren't part of the ranking (like "SOO GAY" or
    members' custom roles, in their current relative order), then Prestige 10 -> 1, then Level 100 -> 0."""
    remaining = list(below)

    def take(names: list[str]) -> list:
        found = []
        for name in names:
            role = match_role(remaining, name)
            if role is not None:
                found.append(role)
                remaining.remove(role)
        return found

    upper = take(upper_rank_names())
    lower = take(lower_rank_names())
    return upper + remaining + lower


async def arrange_roles(guild: discord.Guild) -> int:
    """Put the roles in the order above. Returns how many roles moved.
    Only roles below the bot's own top role can be moved, so the bot's role must stay high."""
    top = guild.me.top_role
    below = sorted(
        (r for r in guild.roles if 0 < r.position < top.position), key=lambda r: r.position, reverse=True
    )
    order = desired_order(below)
    count = len(order)
    moves = {role: count - index for index, role in enumerate(order)}  # highest gets `count`, lowest gets 1
    moves = {role: pos for role, pos in moves.items() if role.position != pos}
    if moves:
        await guild.edit_role_positions(moves, reason="Arranging staff / level roles")
    return len(moves)
