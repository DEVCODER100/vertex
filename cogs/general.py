"""Basic utility commands."""

import discord
from discord import app_commands
from discord.ext import commands

import config


NEEDED_PERMISSIONS = {
    "view_channel": "View Channels",
    "send_messages": "Send Messages",
    "embed_links": "Embed Links",
    "read_message_history": "Read Message History",
    "manage_messages": "Manage Messages (removes GIFs/pictures sent too early)",
    "manage_roles": "Manage Roles (level rewards, shop, custom roles)",
}


def permission_report(server: discord.Permissions, here: discord.Permissions) -> tuple[list[str], list[str]]:
    """Compare the bot's server-wide permissions with what it can do in one channel.
    Returns (one status line per permission, hints on how to fix whatever is missing)."""
    lines, hints = [], []
    for attr, label in NEEDED_PERMISSIONS.items():
        has_server, has_here = getattr(server, attr), getattr(here, attr)
        lines.append(f"{'✅' if has_here else '❌'} {label}")
        if not has_server:
            hints.append(f"**{label.split(' (')[0]}**: the bot's role doesn't have it. Server Settings → Roles → the bot's role → turn it on.")
        elif not has_here:
            hints.append(f"**{label.split(' (')[0]}**: the role has it, but this channel (or its category) blocks it. Edit Channel → Permissions.")
    return lines, hints


HELP_SECTIONS = [
    ("💰 Money & levels", ["Economy", "Leveling", "Prestige", "Leaderboard"]),
    ("🛒 Shop & roles", ["Shop", "CustomRoles"]),
    ("🎲 Gambling", ["Gambling"]),
    ("🎧 Voice", ["PrivateVC"]),
    ("💞 Family", ["Relationships"]),
    ("🤗 Actions & vibes", ["Social", "Vibes"]),
    ("🧰 Other", ["Afk", "General", "Quiz"]),
]


def is_admin_command(cmd: commands.Command) -> bool:
    return any("has_permissions" in repr(check) for check in cmd.checks)


def describe_command(cmd: commands.Command) -> str:
    """`,balance` (bal, b, wallet)  -  and for groups, their sub-commands."""
    text = f"`{config.PREFIX}{cmd.name}`"
    if cmd.aliases:
        text += " (" + ", ".join(cmd.aliases[:3]) + ")"
    if isinstance(cmd, commands.Group):
        subs = sorted(sub.name for sub in cmd.commands if not is_admin_command(sub))
        if subs:
            text += " → " + "/".join(subs)
    return text


def fit(entries: list[str], limit: int = 1000) -> str:
    """Join entries for one embed field, never exceeding Discord's 1024-character field limit."""
    out, size = [], 0
    for entry in entries:
        if size + len(entry) + 3 > limit:
            out.append("…")
            break
        out.append(entry)
        size += len(entry) + 3
    return " · ".join(out) or "nothing here"


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="checkperms", aliases=["perms"], description="Admin: check what the bot is allowed to do in this channel.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def checkperms(self, ctx: commands.Context) -> None:
        me = ctx.guild.me
        lines, hints = permission_report(me.guild_permissions, ctx.channel.permissions_for(me))
        roles = ", ".join(r.mention for r in me.roles if not r.is_default()) or "none"
        embed = discord.Embed(
            title=f"Bot permissions in #{ctx.channel.name}",
            description="\n".join(lines),
            color=discord.Color.red() if hints else discord.Color.green(),
        )
        embed.add_field(name="Bot's roles", value=roles, inline=False)
        embed.add_field(
            name="How to fix" if hints else "All good",
            value="\n".join(hints) if hints else "The bot has everything it needs here.",
            inline=False,
        )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="ping", aliases=["p"], description="Check that the bot is alive.")
    async def ping(self, ctx: commands.Context) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 `{latency_ms} ms`")

    @commands.hybrid_command(
        name="help", aliases=["h", "commands", "cmds"], description="See every command and its short form."
    )
    async def help(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="Commands",
            description=f"Short forms are in (brackets): `{config.PREFIX}balance` = `{config.PREFIX}bal` = `{config.PREFIX}b`.",
            color=discord.Color.blurple(),
        )
        for title, cog_names in HELP_SECTIONS:
            entries = [
                describe_command(cmd)
                for name in cog_names
                if (cog := self.bot.get_cog(name)) is not None
                for cmd in sorted(cog.get_commands(), key=lambda c: c.name)
                if not is_admin_command(cmd)
            ]
            if entries:
                embed.add_field(name=title, value=fit(entries), inline=False)

        is_admin = isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator
        if is_admin:
            admin_entries = [
                describe_command(cmd)
                for cog in self.bot.cogs.values()
                for cmd in sorted(cog.get_commands(), key=lambda c: c.name)
                if is_admin_command(cmd)
            ]
            embed.add_field(name="🔧 Admin only", value=fit(admin_entries), inline=False)
        embed.set_footer(text="Slash commands work too (type /). Your own role: ,cr")
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
