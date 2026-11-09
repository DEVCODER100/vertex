"""Async SQLite storage for XP, levels and both currencies."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiosqlite

import config
from levels import level_from_xp, total_xp_for_level

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    xp            INTEGER NOT NULL DEFAULT 0,
    level         INTEGER NOT NULL DEFAULT 0,
    coins         INTEGER NOT NULL DEFAULT 0,
    credits       INTEGER NOT NULL DEFAULT 0,
    last_daily_at INTEGER NOT NULL DEFAULT 0,
    prestige      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level    INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS prestige_roles (
    guild_id INTEGER NOT NULL,
    prestige INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, prestige)
);

CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL COLLATE NOCASE,
    description TEXT    NOT NULL DEFAULT '',
    price       INTEGER NOT NULL,
    currency    TEXT    NOT NULL CHECK (currency IN ('coins', 'credits')),
    role_id     INTEGER NOT NULL,
    UNIQUE (guild_id, name)
);

CREATE TABLE IF NOT EXISTS custom_roles (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Friends a member has shared their custom role with.
CREATE TABLE IF NOT EXISTS custom_role_friends (
    guild_id  INTEGER NOT NULL,
    owner_id  INTEGER NOT NULL,
    friend_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, owner_id, friend_id)
);

-- A marriage is stored as two rows (a -> b and b -> a) so lookups are a primary-key hit.
CREATE TABLE IF NOT EXISTS marriages (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    partner_id INTEGER NOT NULL,
    married_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- A child has at most one parent; a parent can have many children.
CREATE TABLE IF NOT EXISTS adoptions (
    guild_id   INTEGER NOT NULL,
    child_id   INTEGER NOT NULL,
    parent_id  INTEGER NOT NULL,
    adopted_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, child_id)
);

CREATE TABLE IF NOT EXISTS afk (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    reason   TEXT    NOT NULL DEFAULT 'AFK',
    since    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Who pinged an AFK user while they were away (shown when they come back).
CREATE TABLE IF NOT EXISTS afk_pings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    pinger_id  INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

-- Join-to-create voice: the "hub" channel people join, and the private channels made from it.
CREATE TABLE IF NOT EXISTS vc_hubs (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS temp_vcs (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    guild_id INTEGER NOT NULL,
    from_id  INTEGER NOT NULL,
    to_id    INTEGER NOT NULL,
    action   TEXT    NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, from_id, to_id, action)
);
"""

LEADERBOARD_COLUMNS = {"xp", "coins", "credits"}


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        # One connection is shared, so multi-step changes take this lock to stay atomic.
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        # Databases made before prestige existed need the new column.
        cur = await self._conn.execute("PRAGMA table_info(users)")
        if "prestige" not in {row["name"] for row in await cur.fetchall()}:
            await self._conn.execute("ALTER TABLE users ADD COLUMN prestige INTEGER NOT NULL DEFAULT 0")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def _ensure(self, guild_id: int, user_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id)
        )

    # ---- users ---------------------------------------------------------

    async def get_user(self, guild_id: int, user_id: int) -> aiosqlite.Row:
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "SELECT * FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            await self.conn.commit()
        return row

    async def add_xp(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, int]:
        """Add XP. Returns (old_level, new_level, total_xp)."""
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "SELECT xp, level FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            # XP stops at the level cap; to keep progressing you `,prestige`.
            total = min(row["xp"] + amount, total_xp_for_level(config.MAX_LEVEL))
            new_level = level_from_xp(total)
            await self.conn.execute(
                "UPDATE users SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
                (total, new_level, guild_id, user_id),
            )
            await self.conn.commit()
        return row["level"], new_level, total

    async def set_level(self, guild_id: int, user_id: int, level: int) -> tuple[int, int]:
        """Set a member to exactly `level` (progress inside the level resets to 0).
        Returns (old_level, new_level)."""
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "SELECT level FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            old_level = (await cur.fetchone())["level"]
            await self.conn.execute(
                "UPDATE users SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
                (total_xp_for_level(level), level, guild_id, user_id),
            )
            await self.conn.commit()
        return old_level, level

    async def prestige_up(self, guild_id: int, user_id: int) -> int | None:
        """Prestige a member who is at the max level: back to the start level, prestige + 1.
        Returns the new prestige, or None if they aren't eligible (checked atomically)."""
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "SELECT level, prestige FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            if row["level"] < config.MAX_LEVEL or row["prestige"] >= config.MAX_PRESTIGE:
                return None
            new_prestige = row["prestige"] + 1
            await self.conn.execute(
                "UPDATE users SET prestige = ?, level = ?, xp = ? WHERE guild_id = ? AND user_id = ?",
                (new_prestige, config.PRESTIGE_START_LEVEL, total_xp_for_level(config.PRESTIGE_START_LEVEL), guild_id, user_id),
            )
            await self.conn.commit()
        return new_prestige

    async def set_prestige(self, guild_id: int, user_id: int, prestige: int) -> tuple[int, int]:
        """Admin tool: set the prestige number only. Returns (old, new)."""
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "SELECT prestige FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            old = (await cur.fetchone())["prestige"]
            await self.conn.execute(
                "UPDATE users SET prestige = ? WHERE guild_id = ? AND user_id = ?", (prestige, guild_id, user_id)
            )
            await self.conn.commit()
        return old, prestige

    async def all_levels(self, guild_id: int) -> dict[int, aiosqlite.Row]:
        """{user_id: row with level and prestige} for everyone in the server."""
        cur = await self.conn.execute(
            "SELECT user_id, level, prestige FROM users WHERE guild_id = ?", (guild_id,)
        )
        return {row["user_id"]: row for row in await cur.fetchall()}

    async def set_prestige_role(self, guild_id: int, prestige: int, role_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO prestige_roles (guild_id, prestige, role_id) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, prestige) DO UPDATE SET role_id = excluded.role_id",
                (guild_id, prestige, role_id),
            )
            await self.conn.commit()

    async def prestige_roles(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT prestige, role_id FROM prestige_roles WHERE guild_id = ? ORDER BY prestige", (guild_id,)
        )
        return await cur.fetchall()

    async def add_balance(
        self, guild_id: int, user_id: int, coins: int = 0, credits: int = 0
    ) -> aiosqlite.Row:
        """Add (or subtract, if negative) coins/credits. Balances never drop below 0."""
        async with self._lock:
            await self._ensure(guild_id, user_id)
            await self.conn.execute(
                "UPDATE users SET coins = MAX(0, coins + ?), credits = MAX(0, credits + ?) "
                "WHERE guild_id = ? AND user_id = ?",
                (coins, credits, guild_id, user_id),
            )
            cur = await self.conn.execute(
                "SELECT * FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            await self.conn.commit()
        return row

    async def try_spend(self, guild_id: int, user_id: int, coins: int = 0, credits: int = 0) -> bool:
        """Subtract the amounts only if the user can afford both. For shop/gambling."""
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "UPDATE users SET coins = coins - ?, credits = credits - ? "
                "WHERE guild_id = ? AND user_id = ? AND coins >= ? AND credits >= ?",
                (coins, credits, guild_id, user_id, coins, credits),
            )
            await self.conn.commit()
        return cur.rowcount == 1

    async def transfer_coins(self, guild_id: int, from_id: int, to_id: int, amount: int) -> bool:
        async with self._lock:
            await self._ensure(guild_id, from_id)
            await self._ensure(guild_id, to_id)
            cur = await self.conn.execute(
                "UPDATE users SET coins = coins - ? WHERE guild_id = ? AND user_id = ? AND coins >= ?",
                (amount, guild_id, from_id, amount),
            )
            if cur.rowcount != 1:
                await self.conn.rollback()
                return False
            await self.conn.execute(
                "UPDATE users SET coins = coins + ? WHERE guild_id = ? AND user_id = ?",
                (amount, guild_id, to_id),
            )
            await self.conn.commit()
        return True

    async def claim_daily(
        self, guild_id: int, user_id: int, amount: int, cooldown_seconds: int
    ) -> tuple[bool, int]:
        """Returns (True, new_balance) on success, or (False, seconds_left) if not ready."""
        now = int(time.time())
        async with self._lock:
            await self._ensure(guild_id, user_id)
            cur = await self.conn.execute(
                "SELECT coins, last_daily_at FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            elapsed = now - row["last_daily_at"]
            if elapsed < cooldown_seconds:
                await self.conn.commit()
                return False, cooldown_seconds - elapsed
            await self.conn.execute(
                "UPDATE users SET coins = coins + ?, last_daily_at = ? WHERE guild_id = ? AND user_id = ?",
                (amount, now, guild_id, user_id),
            )
            await self.conn.commit()
        return True, row["coins"] + amount

    # ---- leaderboards --------------------------------------------------

    async def top(self, guild_id: int, column: str, limit: int = 10) -> list[aiosqlite.Row]:
        if column not in LEADERBOARD_COLUMNS:
            raise ValueError(f"Unknown leaderboard column: {column}")
        if column == "xp":  # prestige outranks XP, since XP resets when you prestige
            where, order = "(xp > 0 OR prestige > 0)", "prestige DESC, xp DESC"
        else:
            where, order = f"{column} > 0", f"{column} DESC"
        cur = await self.conn.execute(
            f"SELECT user_id, {column} AS value, level, prestige FROM users "
            f"WHERE guild_id = ? AND {where} ORDER BY {order} LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def users_at_least(self, guild_id: int, level: int) -> list[aiosqlite.Row]:
        """Everyone in the server at or above `level` (highest first)."""
        cur = await self.conn.execute(
            "SELECT user_id, level FROM users WHERE guild_id = ? AND level >= ? ORDER BY level DESC",
            (guild_id, level),
        )
        return await cur.fetchall()

    async def rank_of(self, guild_id: int, user_id: int, column: str) -> int:
        """1-based position of the user on a leaderboard."""
        if column not in LEADERBOARD_COLUMNS:
            raise ValueError(f"Unknown leaderboard column: {column}")
        if column == "xp":  # higher prestige first, then XP
            mine_p = "COALESCE((SELECT prestige FROM users WHERE guild_id = ? AND user_id = ?), 0)"
            mine_x = "COALESCE((SELECT xp FROM users WHERE guild_id = ? AND user_id = ?), 0)"
            cur = await self.conn.execute(
                f"SELECT COUNT(*) + 1 AS pos FROM users WHERE guild_id = ? AND "
                f"(prestige > {mine_p} OR (prestige = {mine_p} AND xp > {mine_x}))",
                (guild_id, guild_id, user_id, guild_id, user_id, guild_id, user_id),
            )
            return (await cur.fetchone())["pos"]
        cur = await self.conn.execute(
            f"SELECT COUNT(*) + 1 AS pos FROM users WHERE guild_id = ? AND {column} > "
            f"(SELECT COALESCE((SELECT {column} FROM users WHERE guild_id = ? AND user_id = ?), 0))",
            (guild_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        return row["pos"]

    # ---- level role rewards -------------------------------------------

    async def set_level_role(self, guild_id: int, level: int, role_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
                (guild_id, level, role_id),
            )
            await self.conn.commit()

    async def remove_level_role(self, guild_id: int, level: int) -> bool:
        async with self._lock:
            cur = await self.conn.execute(
                "DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (guild_id, level)
            )
            await self.conn.commit()
        return cur.rowcount > 0

    async def level_roles(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level", (guild_id,)
        )
        return await cur.fetchall()

    # ---- shop ----------------------------------------------------------

    async def upsert_shop_item(
        self, guild_id: int, name: str, description: str, price: int, currency: str, role_id: int
    ) -> None:
        """Add an item, or update it if one with the same name (any case) already exists."""
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO shop_items (guild_id, name, description, price, currency, role_id) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, name) DO UPDATE SET "
                "description = excluded.description, price = excluded.price, "
                "currency = excluded.currency, role_id = excluded.role_id",
                (guild_id, name, description, price, currency, role_id),
            )
            await self.conn.commit()

    async def remove_shop_item(self, guild_id: int, name: str) -> bool:
        async with self._lock:
            cur = await self.conn.execute(
                "DELETE FROM shop_items WHERE guild_id = ? AND name = ?", (guild_id, name)
            )
            await self.conn.commit()
        return cur.rowcount > 0

    async def shop_items(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM shop_items WHERE guild_id = ? ORDER BY currency DESC, price", (guild_id,)
        )
        return await cur.fetchall()

    async def get_shop_item(self, guild_id: int, name: str) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            "SELECT * FROM shop_items WHERE guild_id = ? AND name = ?", (guild_id, name.strip())
        )
        return await cur.fetchone()

    # ---- custom roles --------------------------------------------------

    async def set_custom_role(self, guild_id: int, user_id: int, role_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO custom_roles (guild_id, user_id, role_id) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET role_id = excluded.role_id",
                (guild_id, user_id, role_id),
            )
            await self.conn.commit()

    async def get_custom_role(self, guild_id: int, user_id: int) -> int | None:
        cur = await self.conn.execute(
            "SELECT role_id FROM custom_roles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row["role_id"] if row else None

    async def delete_custom_role(self, guild_id: int, user_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "DELETE FROM custom_role_friends WHERE guild_id = ? AND owner_id = ?", (guild_id, user_id)
            )
            await self.conn.execute(
                "DELETE FROM custom_roles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            await self.conn.commit()

    async def delete_custom_role_by_role(self, guild_id: int, role_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "DELETE FROM custom_role_friends WHERE guild_id = ? AND owner_id IN "
                "(SELECT user_id FROM custom_roles WHERE guild_id = ? AND role_id = ?)",
                (guild_id, guild_id, role_id),
            )
            await self.conn.execute(
                "DELETE FROM custom_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
            )
            await self.conn.commit()

    async def get_custom_role_owner(self, guild_id: int, role_id: int) -> int | None:
        cur = await self.conn.execute(
            "SELECT user_id FROM custom_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
        )
        row = await cur.fetchone()
        return row["user_id"] if row else None

    # ---- sharing a custom role with friends ----------------------------------

    async def add_custom_friend(self, guild_id: int, owner_id: int, friend_id: int, limit: int) -> bool:
        """Share with a friend. False if they already have it or the owner is at their limit (checked atomically)."""
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT COUNT(*) AS n FROM custom_role_friends WHERE guild_id = ? AND owner_id = ?",
                (guild_id, owner_id),
            )
            if (await cur.fetchone())["n"] >= limit:
                return False
            cur = await self.conn.execute(
                "INSERT OR IGNORE INTO custom_role_friends (guild_id, owner_id, friend_id) VALUES (?, ?, ?)",
                (guild_id, owner_id, friend_id),
            )
            await self.conn.commit()
        return cur.rowcount == 1

    async def remove_custom_friend(self, guild_id: int, owner_id: int, friend_id: int) -> bool:
        async with self._lock:
            cur = await self.conn.execute(
                "DELETE FROM custom_role_friends WHERE guild_id = ? AND owner_id = ? AND friend_id = ?",
                (guild_id, owner_id, friend_id),
            )
            await self.conn.commit()
        return cur.rowcount > 0

    async def custom_friends(self, guild_id: int, owner_id: int) -> list[int]:
        cur = await self.conn.execute(
            "SELECT friend_id FROM custom_role_friends WHERE guild_id = ? AND owner_id = ?", (guild_id, owner_id)
        )
        return [row["friend_id"] for row in await cur.fetchall()]

    async def forget_custom_friend(self, guild_id: int, friend_id: int) -> None:
        """A member left the server: free up the slot they were using on everyone's role."""
        async with self._lock:
            await self.conn.execute(
                "DELETE FROM custom_role_friends WHERE guild_id = ? AND friend_id = ?", (guild_id, friend_id)
            )
            await self.conn.commit()

    # ---- marriage ------------------------------------------------------

    async def marry(self, guild_id: int, user_a: int, user_b: int) -> bool:
        """Marry two people. False if either is already married (checked atomically)."""
        now = int(time.time())
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT COUNT(*) AS n FROM marriages WHERE guild_id = ? AND user_id IN (?, ?)",
                (guild_id, user_a, user_b),
            )
            if (await cur.fetchone())["n"]:
                return False
            await self.conn.executemany(
                "INSERT INTO marriages (guild_id, user_id, partner_id, married_at) VALUES (?, ?, ?, ?)",
                [(guild_id, user_a, user_b, now), (guild_id, user_b, user_a, now)],
            )
            await self.conn.commit()
        return True

    async def get_marriage(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            "SELECT partner_id, married_at FROM marriages WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def divorce(self, guild_id: int, user_id: int) -> int | None:
        """End the user's marriage. Returns the ex-partner's id, or None if they weren't married."""
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT partner_id FROM marriages WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await self.conn.execute(
                "DELETE FROM marriages WHERE guild_id = ? AND user_id IN (?, ?)",
                (guild_id, user_id, row["partner_id"]),
            )
            await self.conn.commit()
        return row["partner_id"]

    # ---- adoption ------------------------------------------------------

    async def adopt(self, guild_id: int, parent_id: int, child_id: int) -> bool:
        """False if the child already has a parent."""
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT OR IGNORE INTO adoptions (guild_id, child_id, parent_id, adopted_at) VALUES (?, ?, ?, ?)",
                (guild_id, child_id, parent_id, int(time.time())),
            )
            await self.conn.commit()
        return cur.rowcount == 1

    async def get_parent(self, guild_id: int, child_id: int) -> int | None:
        cur = await self.conn.execute(
            "SELECT parent_id FROM adoptions WHERE guild_id = ? AND child_id = ?", (guild_id, child_id)
        )
        row = await cur.fetchone()
        return row["parent_id"] if row else None

    async def get_children(self, guild_id: int, parent_id: int) -> list[int]:
        cur = await self.conn.execute(
            "SELECT child_id FROM adoptions WHERE guild_id = ? AND parent_id = ? ORDER BY adopted_at",
            (guild_id, parent_id),
        )
        return [row["child_id"] for row in await cur.fetchall()]

    async def remove_adoption(self, guild_id: int, child_id: int) -> bool:
        async with self._lock:
            cur = await self.conn.execute(
                "DELETE FROM adoptions WHERE guild_id = ? AND child_id = ?", (guild_id, child_id)
            )
            await self.conn.commit()
        return cur.rowcount > 0

    # ---- join-to-create voice ------------------------------------------

    async def add_vc_hub(self, guild_id: int, channel_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT OR REPLACE INTO vc_hubs (channel_id, guild_id) VALUES (?, ?)", (channel_id, guild_id)
            )
            await self.conn.commit()

    async def all_vc_hubs(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM vc_hubs")
        return await cur.fetchall()

    async def remove_vc_hub(self, channel_id: int) -> None:
        async with self._lock:
            await self.conn.execute("DELETE FROM vc_hubs WHERE channel_id = ?", (channel_id,))
            await self.conn.commit()

    async def add_temp_vc(self, guild_id: int, channel_id: int, owner_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT OR REPLACE INTO temp_vcs (channel_id, guild_id, owner_id) VALUES (?, ?, ?)",
                (channel_id, guild_id, owner_id),
            )
            await self.conn.commit()

    async def all_temp_vcs(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM temp_vcs")
        return await cur.fetchall()

    async def set_temp_vc_owner(self, channel_id: int, owner_id: int) -> None:
        async with self._lock:
            await self.conn.execute("UPDATE temp_vcs SET owner_id = ? WHERE channel_id = ?", (owner_id, channel_id))
            await self.conn.commit()

    async def remove_temp_vc(self, channel_id: int) -> None:
        async with self._lock:
            await self.conn.execute("DELETE FROM temp_vcs WHERE channel_id = ?", (channel_id,))
            await self.conn.commit()

    # ---- AFK -----------------------------------------------------------

    async def set_afk(self, guild_id: int, user_id: int, reason: str) -> aiosqlite.Row:
        """Go AFK (or change the reason if already AFK; the original start time is kept)."""
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO afk (guild_id, user_id, reason, since) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET reason = excluded.reason",
                (guild_id, user_id, reason, int(time.time())),
            )
            cur = await self.conn.execute(
                "SELECT * FROM afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            await self.conn.commit()
        return row

    async def all_afk(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM afk")
        return await cur.fetchall()

    async def clear_afk(self, guild_id: int, user_id: int) -> tuple[aiosqlite.Row | None, list[aiosqlite.Row]]:
        """End AFK. Returns (the AFK record, the pings received while away), or (None, []) if not AFK."""
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT * FROM afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            record = await cur.fetchone()
            if record is None:
                return None, []
            cur = await self.conn.execute(
                "SELECT * FROM afk_pings WHERE guild_id = ? AND user_id = ? ORDER BY id", (guild_id, user_id)
            )
            pings = await cur.fetchall()
            await self.conn.execute("DELETE FROM afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            await self.conn.execute("DELETE FROM afk_pings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            await self.conn.commit()
        return record, pings

    async def add_afk_ping(
        self, guild_id: int, user_id: int, pinger_id: int, channel_id: int, message_id: int, keep: int = 25
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO afk_pings (guild_id, user_id, pinger_id, channel_id, message_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, pinger_id, channel_id, message_id, int(time.time())),
            )
            # keep only the newest `keep` pings per AFK user
            await self.conn.execute(
                "DELETE FROM afk_pings WHERE guild_id = ? AND user_id = ? AND id NOT IN "
                "(SELECT id FROM afk_pings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?)",
                (guild_id, user_id, guild_id, user_id, keep),
            )
            await self.conn.commit()

    # ---- interaction counters ------------------------------------------

    async def bump_interaction(self, guild_id: int, from_id: int, to_id: int, action: str) -> int:
        """Count one more `action` from -> to. Returns the new total for that pair."""
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO interactions (guild_id, from_id, to_id, action, count) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(guild_id, from_id, to_id, action) DO UPDATE SET count = count + 1",
                (guild_id, from_id, to_id, action),
            )
            cur = await self.conn.execute(
                "SELECT count FROM interactions WHERE guild_id = ? AND from_id = ? AND to_id = ? AND action = ?",
                (guild_id, from_id, to_id, action),
            )
            row = await cur.fetchone()
            await self.conn.commit()
        return row["count"]
