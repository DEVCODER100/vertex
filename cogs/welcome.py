"""Greets new members (and optionally says goodbye when they leave)."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("vertex.welcome")


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---- helpers -------------------------------------------------------

    def _find_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Configured welcome channel, else the server's system channel."""
        channel = guild.get_channel(config.WELCOME_CHANNEL_ID) if config.WELCOME_CHANNEL_ID else None
        channel = channel or guild.system_channel

        if channel is None:
            log.warning("No welcome channel for %s. Set WELCOME_CHANNEL_ID in .env.", guild.name)
            return None
        if not channel.permissions_for(guild.me).send_messages:
            log.warning("Missing permission to send messages in #%s (%s).", channel.name, guild.name)
            return None
        return channel

    @staticmethod
    def _welcome_embed(member: discord.Member) -> discord.Embed:
        guild = member.guild
        embed = discord.Embed(
            title=f"Welcome to {guild.name}! 🎮",
            description=(
                f"Hey {member.mention}, glad you made it!\n"
                "Grab a spot, say hi, and let us know what you're playing."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"You're member #{guild.member_count}")
        return embed

    async def _send_welcome(self, member: discord.Member) -> bool:
        channel = self._find_channel(member.guild)
        if channel is None:
            return False
        await channel.send(content=member.mention, embed=self._welcome_embed(member))
        return True

    # ---- events --------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        try:
            await self._send_welcome(member)
        except discord.HTTPException:
            log.exception("Failed to send welcome message for %s", member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not config.SEND_GOODBYE or member.bot:
            return
        channel = self._find_channel(member.guild)
        if channel is None:
            return
        try:
            await channel.send(f"**{member.display_name}** has left the server. See you around! 👋")
        except discord.HTTPException:
            log.exception("Failed to send goodbye message for %s", member)

    # ---- commands ------------------------------------------------------

    @app_commands.command(name="testwelcome", description="Preview the welcome message (admins only).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def testwelcome(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        sent = await self._send_welcome(interaction.user)
        if sent:
            await interaction.followup.send("Welcome message sent! ✅", ephemeral=True)
        else:
            await interaction.followup.send(
                "I couldn't post it — set `WELCOME_CHANNEL_ID` in `.env` and make sure I can "
                "send messages in that channel.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
