"""XP -> level math. Pure functions, no Discord or database code."""


def effective_level(level: int, prestige: int) -> int:
    """Level used for unlocks (GIFs, custom roles). Anyone who has prestiged counts as max level."""
    import config

    return config.MAX_LEVEL if prestige > 0 else level


def xp_to_next(level: int) -> int:
    """XP needed to go from `level` to `level + 1`."""
    return 5 * level * level + 50 * level + 100


def total_xp_for_level(level: int) -> int:
    """Total XP a member has when they just reach `level` (0 progress into it)."""
    return sum(xp_to_next(i) for i in range(level))


def level_from_xp(total_xp: int) -> int:
    level = 0
    remaining = total_xp
    while remaining >= xp_to_next(level):
        remaining -= xp_to_next(level)
        level += 1
    return level


def progress(total_xp: int) -> tuple[int, int, int]:
    """Return (level, xp gained inside this level, xp needed to finish this level)."""
    level = 0
    remaining = total_xp
    while remaining >= xp_to_next(level):
        remaining -= xp_to_next(level)
        level += 1
    return level, remaining, xp_to_next(level)
