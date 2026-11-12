"""Dead-chat pinger.

Every 60-90 minutes the bot checks the lounge. If 3+ different people talked in the last 30 minutes
the chat is alive and it stays quiet; if it's silent or only 1-2 people are around, it posts an
@everyone with a random line. It never pings a specific member. Quiet hours (IST) skip the night.
Needs the Mention Everyone permission for the bot (see ,lockeveryone).
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from rolesutil import norm_name

CHANNEL_NAME = "lounge"       # matched with emojis/symbols ignored, like the rest of the bot
WINDOW_MINUTES = 30           # "recent" chat = the last 30 minutes
ACTIVE_CHATTERS = 3           # this many different people talking in the window = chat is alive, no ping
COOLDOWN_RANGE = (60, 90)     # minutes between two bot pings (random, so it isn't robotic)
QUIET_FROM, QUIET_TO = 1, 9   # no pings from 01:00 to 09:00 IST (people are asleep)
IST = timezone(timedelta(hours=5, minutes=30))

GENERIC = [
    "@everyone get active, this chat is a graveyard 💀",
    "@everyone come online, it's way too quiet in here",
    "@everyone wake up! someone say something, anything",
    "@everyone chat is dead. Revive it with a hello 👋",
    "@everyone who's up for a game? drop your answer below 🎮",
    "@everyone touch some grass, then come back and tell us about it",
    "@everyone *tumbleweed rolls by* ... talk to each other!",
    "@everyone drop your most random thought of the day 👇",
    "@everyone beba is gay",
]

def pick_line() -> str:
    """A random @everyone line. It never pings a specific member."""
    return random.choice(GENERIC)


def in_quiet_hours(now: datetime) -> bool:
    h = now.astimezone(IST).hour
    return QUIET_FROM <= h < QUIET_TO


class DeadChat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.enabled = True
        self._recent: dict[int, list[tuple[float, int]]] = {}   # channel id -> [(time, author id)] of human messages
        self._last_ping: float = time.monotonic()                # first ping comes one cooldown after start
        self._next_gap: float = random.uniform(*COOLDOWN_RANGE) * 60

    def _chatters(self, channel_id: int, now: float) -> int:
        """How many different people talked in the last WINDOW_MINUTES."""
        cutoff = now - WINDOW_MINUTES * 60
        msgs = [m for m in self._recent.get(channel_id, []) if m[0] >= cutoff]
        self._recent[channel_id] = msgs
        return len({a for _, a in msgs})

    async def cog_load(self) -> None:
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()

    def _channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        for ch in guild.text_channels:
            if norm_name(ch.name) == CHANNEL_NAME:
                return ch
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        self._recent.setdefault(message.channel.id, []).append((time.monotonic(), message.author.id))

    async def _send_ping(self, channel: discord.TextChannel) -> bool:
        me = channel.guild.me
        perms = channel.permissions_for(me)
        if not perms.send_messages:
            return False
        text = pick_line()
        allowed = discord.AllowedMentions(everyone=perms.mention_everyone, users=False, roles=False)
        try:
            await channel.send(text, allowed_mentions=allowed)
        except discord.HTTPException:
            return False
        self._last_ping = time.monotonic()
        self._next_gap = random.uniform(*COOLDOWN_RANGE) * 60
        return True

    @tasks.loop(minutes=5)
    async def watch(self) -> None:
        if not self.enabled or in_quiet_hours(datetime.now(timezone.utc)):
            return
        now = time.monotonic()
        if now - self._last_ping < self._next_gap:
            return
        for guild in self.bot.guilds:
            channel = self._channel(guild)
            if channel is None:
                continue
            # silent, or only 1-2 people around = dead; 3+ people talking = alive, skip (checked again in 5 min)
            if self._chatters(channel.id, now) < ACTIVE_CHATTERS:
                await self._send_ping(channel)
                return

    @watch.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    @commands.hybrid_group(name="deadchat", aliases=["wakeup"], invoke_without_command=True,
                           description="Auto-ping the lounge when chat is dead.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def deadchat(self, ctx: commands.Context) -> None:
        state = "ON" if self.enabled else "OFF"
        await ctx.send(
            f"Dead-chat pinger is **{state}**. Every {COOLDOWN_RANGE[0]}-{COOLDOWN_RANGE[1]} min it pings @everyone in the lounge "
            f"unless {ACTIVE_CHATTERS}+ people chatted in the last {WINDOW_MINUTES} min (never 0{QUIET_FROM}:00-0{QUIET_TO}:00 IST).\n"
            "Use `,deadchat on`, `,deadchat off` or `,deadchat test`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @deadchat.command(name="on", description="Turn the dead-chat pinger on.")
    async def dc_on(self, ctx: commands.Context) -> None:
        self.enabled = True
        await ctx.send("Dead-chat pinger is **ON** (until the bot restarts).")

    @deadchat.command(name="off", description="Turn the dead-chat pinger off.")
    async def dc_off(self, ctx: commands.Context) -> None:
        self.enabled = False
        await ctx.send("Dead-chat pinger is **OFF** (until the bot restarts).")

    @deadchat.command(name="test", description="Send one dead-chat ping to the lounge right now.")
    async def dc_test(self, ctx: commands.Context) -> None:
        channel = self._channel(ctx.guild)
        if channel is None:
            await ctx.send("I can't find a lounge channel.")
            return
        if not await self._send_ping(channel):
            await ctx.send(f"I couldn't post in {channel.mention}. Check that I can send messages there.")
            return
        if not channel.permissions_for(ctx.guild.me).mention_everyone:
            await ctx.send("Posted, but I don't have **Mention Everyone**, so @everyone didn't ping. Give it to my role.")
        else:
            await ctx.send(f"Sent in {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeadChat(bot))
