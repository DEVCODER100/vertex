"""Level-gated media: GIFs need level 10, pictures need level 20 (staff are exempt)."""

import logging
import time

import discord
from discord.ext import commands

import config
import levels
import media

log = logging.getLogger("vertex.mediagate")

NOTICE_SECONDS = 8            # how long the "you need level X" notice stays up
NOTICE_COOLDOWN_SECONDS = 10  # at most one notice per member per this many seconds


class MediaGate(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_notice: dict[tuple[int, int], float] = {}
        self._warned_no_permission = False

    async def _enforce(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return
        member = message.author
        if not isinstance(member, discord.Member):
            return

        attachments = [(a.filename, a.content_type) for a in message.attachments]
        needed = media.required_level(message.content, attachments)
        if needed is None:
            return
        level_needed, noun = needed

        perms = member.guild_permissions
        if perms.administrator or perms.manage_messages:
            return  # staff can post anything

        row = await self.bot.db.get_user(message.guild.id, member.id)
        if levels.effective_level(row["level"], row["prestige"]) >= level_needed:
            return  # (prestiged members count as max level)

        if not message.channel.permissions_for(message.guild.me).manage_messages:
            if not self._warned_no_permission:
                self._warned_no_permission = True
                log.warning(
                    "I need the Manage Messages permission in #%s to remove GIFs/pictures sent too early. "
                    "Run ,checkperms in that channel to see what's blocking it.",
                    message.channel,
                )
            return

        try:
            await message.delete()
        except discord.HTTPException:
            return  # already deleted, or we can't. Nothing more to do.

        key = (message.guild.id, member.id)
        now = time.monotonic()
        if now - self._last_notice.get(key, -1e9) < NOTICE_COOLDOWN_SECONDS:
            return
        self._last_notice[key] = now
        try:
            await message.channel.send(
                f"🚫 {member.mention}, you need **level {level_needed}** to send {noun}. "
                f"You're level {row['level']}. Keep chatting to level up!",
                delete_after=NOTICE_SECONDS,
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._enforce(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        # Stops "post text first, edit the GIF link in afterwards".
        if before.content != after.content:
            await self._enforce(after)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MediaGate(bot))
