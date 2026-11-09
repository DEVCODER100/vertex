"""AFK: ,afk [reason] -> your next real message ends it, and you're told who pinged you."""

import logging
import time

import discord
from discord.ext import commands

from media import GIF_URL, has_gif, is_gif_file

log = logging.getLogger("vertex.afk")

NOTICE_COOLDOWN_SECONDS = 20     # don't repeat "X is AFK" in the same channel more often than this
MAX_REASON_LENGTH = 100
MAX_PINGS_SHOWN = 10
NO_PINGS = discord.AllowedMentions.none()


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    parts = []
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount} {unit}{'s' if amount != 1 else ''}")
    return ", ".join(parts[:2])  # the two biggest units are plenty: "2 hours, 5 minutes"


def is_gif_only(content: str, attachments: list[tuple[str, str | None]]) -> bool:
    """True if the message is just a GIF (link and/or attached .gif) with no other text or files.
    `attachments` is a list of (filename, content_type)."""
    if not has_gif(content, attachments):
        return False
    leftover_text = GIF_URL.sub("", content).strip()
    return not leftover_text and all(is_gif_file(n, t) for n, t in attachments)


def clean_reason(reason: str) -> str:
    reason = " ".join(reason.split())  # no newlines or runs of spaces
    return discord.utils.escape_mentions(reason)[:MAX_REASON_LENGTH] or "AFK"


class Afk(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.afk: dict[tuple[int, int], tuple[str, int]] = {}  # (guild, user) -> (reason, since)
        self._last_notice: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        for row in await self.bot.db.all_afk():
            self.afk[(row["guild_id"], row["user_id"])] = (row["reason"], row["since"])

    # ---- command -------------------------------------------------------

    @commands.hybrid_command(name="afk", description="Set yourself AFK. Your next message ends it.")
    @commands.guild_only()
    async def afk_command(self, ctx: commands.Context, *, reason: str = "AFK") -> None:
        reason = clean_reason(reason)
        row = await self.bot.db.set_afk(ctx.guild.id, ctx.author.id, reason)
        self.afk[(ctx.guild.id, ctx.author.id)] = (row["reason"], row["since"])
        await ctx.send(f"💤 {ctx.author.mention}, I set you as AFK: **{reason}**", allowed_mentions=NO_PINGS)

    # ---- listener ------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        await self._handle_return(message)
        await self._handle_mentions(message)

    async def _is_afk_command(self, message: discord.Message) -> bool:
        ctx = await self.bot.get_context(message)
        return ctx.command is not None and ctx.command.qualified_name == "afk"

    async def _handle_return(self, message: discord.Message) -> None:
        key = (message.guild.id, message.author.id)
        if key not in self.afk:
            return
        if await self._is_afk_command(message):
            return  # running ",afk" must not cancel itself
        attachments = [(a.filename, a.content_type) for a in message.attachments]
        if is_gif_only(message.content, attachments):
            return  # GIFs don't break AFK

        record, pings = await self.bot.db.clear_afk(*key)
        self.afk.pop(key, None)
        if record is None:
            return

        away = format_duration(int(time.time()) - record["since"])
        text = f"👋 Welcome back {message.author.mention}! You were AFK for **{away}**."
        embed = None
        if pings:
            text += f"\nYou were pinged **{len(pings)}** time{'s' if len(pings) != 1 else ''} while you were away:"
            lines = [
                f"<@{p['pinger_id']}> in <#{p['channel_id']}> <t:{p['created_at']}:R> — "
                f"[jump](https://discord.com/channels/{message.guild.id}/{p['channel_id']}/{p['message_id']})"
                for p in pings[-MAX_PINGS_SHOWN:]
            ]
            if len(pings) > MAX_PINGS_SHOWN:
                lines.insert(0, f"*...and {len(pings) - MAX_PINGS_SHOWN} earlier*")
            embed = discord.Embed(description="\n".join(lines), color=discord.Color.blurple())
        try:
            await message.channel.send(text, embed=embed, allowed_mentions=NO_PINGS)
        except discord.HTTPException:
            log.warning("Couldn't send the welcome-back message in %s", message.channel)

    async def _handle_mentions(self, message: discord.Message) -> None:
        notices = []
        for user in message.mentions:
            key = (message.guild.id, user.id)
            if user.id == message.author.id or key not in self.afk:
                continue
            reason, since = self.afk[key]
            await self.bot.db.add_afk_ping(message.guild.id, user.id, message.author.id, message.channel.id, message.id)

            now = time.monotonic()
            if now - self._last_notice.get((message.channel.id, user.id), -1e9) < NOTICE_COOLDOWN_SECONDS:
                continue
            self._last_notice[(message.channel.id, user.id)] = now
            notices.append(f"💤 **{user.display_name}** is AFK: {reason} (since <t:{since}:R>)")

        if notices:
            try:
                await message.reply("\n".join(notices), mention_author=False, allowed_mentions=NO_PINGS)
            except discord.HTTPException:
                log.warning("Couldn't send an AFK notice in %s", message.channel)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Afk(bot))
