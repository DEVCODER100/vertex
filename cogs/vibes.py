"""Daily vibe checks: ,iq  ,aura  ,rizz.

Each member gets one number per check per day. It is worked out from the member's id and today's
date in IST (India time), so it never changes during the day, resets at midnight IST, and needs no
database. Look up someone else by mentioning them.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

IST = timezone(timedelta(hours=5, minutes=30))
BAR_LENGTH = 16


def ist_today(now: datetime | None = None) -> str:
    """Today's date in IST as YYYY-MM-DD (this is what the numbers are keyed on)."""
    return (now or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m-%d")


def next_reset(now: datetime | None = None) -> datetime:
    """The next midnight in IST."""
    local = (now or datetime.now(timezone.utc)).astimezone(IST)
    return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _unit(kind: str, user_id: int, day: str, salt: str) -> float:
    """A stable pseudo-random number in [0, 1) for this member, check and IST day."""
    digest = hashlib.sha256(f"vertex:{kind}:{user_id}:{day}:{salt}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def iq_for(user_id: int, day: str) -> int:
    """60-160, bunched around the middle like a real bell curve (average of three rolls)."""
    avg = sum(_unit("iq", user_id, day, str(i)) for i in range(3)) / 3
    return round(60 + avg * 100)


def percent_for(kind: str, user_id: int, day: str) -> int:
    """0-100 percent."""
    return round(_unit(kind, user_id, day, "0") * 100)


def bar(fraction: float) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * BAR_LENGTH)
    return "▰" * filled + "▱" * (BAR_LENGTH - filled)


def iq_comment(value: int) -> str:
    if value < 80: return "Running on vibes only today."
    if value < 100: return "Solid. Nothing to worry about."
    if value < 120: return "Sharp. Keep it up."
    if value < 140: return "Big brain energy."
    return "Absolute genius. Suspicious, honestly."


def percent_comment(kind: str, value: int) -> str:
    tiers = {
        "aura": ["Aura is in the negatives. Rest up.", "Barely a glow.", "Getting there.", "Strong presence.", "Main character aura."],
        "rizz": ["No rizz today. Try tomorrow.", "A little awkward.", "Decent charm.", "Smooth talker.", "Unspoken rizz god."],
    }[kind]
    return tiers[min(len(tiers) - 1, value // 20)]


KINDS = {
    "iq": {"label": "IQ", "emoji": "🧠", "low": 60, "high": 160},
    "aura": {"label": "Aura", "emoji": "✨", "low": 0, "high": 100},
    "rizz": {"label": "Rizz", "emoji": "😎", "low": 0, "high": 100},
}


def build_embed(kind: str, member: discord.abc.User, now: datetime | None = None) -> discord.Embed:
    info = KINDS[kind]
    day = ist_today(now)
    if kind == "iq":
        value = iq_for(member.id, day)
        headline = f"{member.mention} has an IQ of **{value}**."
        comment = iq_comment(value)
        fraction = (value - info["low"]) / (info["high"] - info["low"])
        scale = f"`60` · `100` · `160`"
    else:
        value = percent_for(kind, member.id, day)
        headline = f"{member.mention} has **{value}%** {kind}."
        comment = percent_comment(kind, value)
        fraction = value / 100
        scale = "`0%` · `50%` · `100%`"
    color = discord.Color.from_hsv(0.0 + 0.33 * fraction, 0.65, 0.95)  # red -> green as it rises
    embed = discord.Embed(
        title=f"{info['emoji']} {member.display_name}'s {info['label']}",
        description=f"{headline}\n\n`{bar(fraction)}`\n{scale}\n\n*{comment}*",
        color=color,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Changes", value=f"<t:{int(next_reset(now).timestamp())}:R> (midnight IST)", inline=False)
    return embed


def pair_percent(kind: str, id_a: int, id_b: int, day: str) -> int:
    """0-100 for two members. Sorted ids, so `A & B` and `B & A` always give the same score."""
    low, high = sorted((id_a, id_b))
    digest = hashlib.sha256(f"vertex:{kind}:{low}:{high}:{day}".encode()).digest()
    return round(int.from_bytes(digest[:8], "big") / 2**64 * 100)


PAIR_KINDS = {
    "ship": {
        "emoji": "💞", "verb": "are **{v}%** compatible.", "color": 0xFF6FA5,
        "tiers": ["Not meant to be. Today, anyway.", "Just friends, for now.", "Some spark here.", "Real chemistry.", "Written in the stars."],
    },
    "bestie": {
        "emoji": "🤝", "verb": "are **{v}%** besties.", "color": 0xF1C40F,
        "tiers": ["Barely know each other.", "Friendly acquaintances.", "Good friends.", "Ride or die.", "Inseparable. Soulmates, basically."],
    },
}


def build_pair_embed(kind: str, a: discord.abc.User, b: discord.abc.User, now: datetime | None = None) -> discord.Embed:
    info = PAIR_KINDS[kind]
    value = pair_percent(kind, a.id, b.id, ist_today(now))
    embed = discord.Embed(
        title=f"{info['emoji']} {a.display_name} & {b.display_name}",
        description=(
            f"{a.mention} & {b.mention} {info['verb'].format(v=value)}\n\n"
            f"`{bar(value / 100)}`\n`0%` · `50%` · `100%`\n\n*{info['tiers'][min(4, value // 20)]}*"
        ),
        color=info["color"],
    )
    embed.set_thumbnail(url=b.display_avatar.url)
    embed.add_field(name="Changes", value=f"<t:{int(next_reset(now).timestamp())}:R> (midnight IST)", inline=False)
    return embed


class Vibes(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _pair(self, ctx: commands.Context, kind: str, first: discord.Member, second: discord.Member | None) -> None:
        a, b = (ctx.author, first) if second is None else (first, second)
        if a.bot or b.bot:
            await ctx.send("Bots can't be part of this one. Pick two people.", ephemeral=True)
            return
        if a.id == b.id:
            await ctx.send("Pick two different people.", ephemeral=True)
            return
        await ctx.send(embed=build_pair_embed(kind, a, b))

    @commands.hybrid_command(name="ship", description="Check how compatible two people are today (changes at midnight IST).")
    @app_commands.describe(member="Who to ship you with (or the first person)", other="Optional second person")
    async def ship(self, ctx: commands.Context, member: discord.Member, other: discord.Member | None = None) -> None:
        await self._pair(ctx, "ship", member, other)

    @commands.hybrid_command(name="bestie", aliases=["bff"], description="Check how good friends two people are today (changes at midnight IST).")
    @app_commands.describe(member="Who to check you with (or the first person)", other="Optional second person")
    async def bestie(self, ctx: commands.Context, member: discord.Member, other: discord.Member | None = None) -> None:
        await self._pair(ctx, "bestie", member, other)

    async def _reply(self, ctx: commands.Context, kind: str, member: discord.Member | None) -> None:
        target = member or ctx.author
        if target.bot:
            await ctx.send("Bots don't have vibes. Try a person.", ephemeral=True)
            return
        await ctx.send(embed=build_embed(kind, target))

    @commands.hybrid_command(name="iq", description="Check your IQ for today (changes at midnight IST).")
    @app_commands.describe(member="Whose IQ to check (default: you)")
    async def iq(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._reply(ctx, "iq", member)

    @commands.hybrid_command(name="aura", description="Check your aura for today (changes at midnight IST).")
    @app_commands.describe(member="Whose aura to check (default: you)")
    async def aura(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._reply(ctx, "aura", member)

    @commands.hybrid_command(name="rizz", description="Check your rizz for today (changes at midnight IST).")
    @app_commands.describe(member="Whose rizz to check (default: you)")
    async def rizz(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._reply(ctx, "rizz", member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Vibes(bot))
