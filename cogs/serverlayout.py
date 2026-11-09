"""Admin tool that builds a tidy server layout: ,setupserver (and ,announce).

It creates categories and channels (rules, announce, roles, lounge, bot channels, media, leaderboards,
levels, voice channels and the Join-to-Create hub). Anything that already exists is left alone, so it's safe
to run again. It never deletes or renames anything.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from rolesutil import norm_name

log = logging.getLogger("vertex.serverlayout")

# (kind, emoji, name, topic, read_only, info)   kind: "text" or "voice"
# info: text posted once in a newly created channel ("rules", "roles", "vcinfo") or "hub" for Join-to-Create.
LAYOUT: list[tuple[str, list[tuple]]] = [
    ("🍄 WELCOME", [
        ("text", "📋", "rules", "Read these before chatting.", True, "rules"),
        ("text", "🔔", "announce", "Server updates and news.", True, None),
        ("text", "🧸", "roles", "How roles, levels and tiers work.", True, "roles"),
    ]),
    ("🌴 SOCIAL", [
        ("text", "💬", "lounge", "Chat with everyone.", False, None),
    ]),
    ("🎮 BOTS", [
        ("text", "🤖", "economy", "Coins and games: ,daily ,bal ,cf ,slots ,bj", False, None),
        ("text", "🤖", "commands", "Use any bot command here. Start with ,help", False, None),
    ]),
    ("🗽 MEDIA", [
        ("text", "📷", "you", "Selfies and pictures of you.", False, None),
        ("text", "🥗", "food", "Show us what you're eating.", False, None),
        ("text", "🐰", "pets", "Got a pet? Post it here.", False, None),
    ]),
    ("🎀 SPECIAL", [
        ("text", "💫", "leaderboards", "Use ,lb to see the top players.", False, None),
        ("text", "🎓", "apply-for-staff", "Want to help run the server? Tell us about yourself and why.", False, None),
        ("text", "🚀", "levels", "Level-up announcements.", True, None),
    ]),
    ("🔊 PUBLIC VC", [("voice", "🔊", f"Voice {i}", None, False, None) for i in range(1, 6)]),
    ("🎯 PRIVATE VC", [
        ("text", "📕", "vc-info", "How your own private voice channel works.", True, "vcinfo"),
        ("voice", "🎧", "Join2Create", None, False, "hub"),
    ]),
]

RULES = [
    "**Be respectful.** No harassment, hate speech, slurs or bullying.",
    "**No spam.** No flooding, repeated messages, or unwanted DMs and ads.",
    "**Keep it clean in public channels.** No NSFW, gore or shock content.",
    "**Protect privacy.** Never share anyone's personal info, and don't dox.",
    "**Use the right channel.** Bot commands in the bot channels, pictures in the media channels.",
    "**No cheating.** Don't abuse bugs or alt accounts to farm coins, XP or levels.",
    "**Listen to staff.** Their decisions are final. Ask politely if you disagree.",
    "**Follow Discord's Terms of Service and Community Guidelines.**",
]


def rules_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📋 Server rules",
        description="\n".join(f"**{i}.** {rule}" for i, rule in enumerate(RULES, 1)),
        color=discord.Color.red(),
    )
    embed.set_footer(text="Breaking the rules can lead to a mute, kick or ban.")
    return embed


def roles_embed() -> discord.Embed:
    embed = discord.Embed(title="🧸 Roles, levels and tiers", color=discord.Color.blurple())
    staff = " › ".join(name for name, _color in config.SERVER_ROLES)
    embed.add_field(name="👑 Staff", value=staff, inline=False)

    tiers = "\n".join(
        f"**{name}**: {price:,} {config.CREDITS_EMOJI} Credits" for name, price, _color in reversed(config.TIER_ROLES)
    )
    embed.add_field(
        name="💎 Premium tiers",
        value=f"Buy them with `{config.PREFIX}shop` and `{config.PREFIX}buy <tier>`.\n{tiers}",
        inline=False,
    )
    limits = ", ".join(f"{tier} {count}" for tier, count in config.TIER_FRIEND_LIMITS.items() if count)
    embed.add_field(
        name="🎨 Your own role",
        value=(
            f"Own any tier? Make your own role with `{config.PREFIX}cr <name>`, then pick its colour and icon "
            f"and share it with friends. Friends you can share with: {limits}."
        ),
        inline=False,
    )
    levels = ", ".join(str(b[0]) for b in config.LEVEL_BADGES if b[0] > 0)
    embed.add_field(
        name="📈 Level badges",
        value=(
            f"Chat to earn XP and you get a badge at levels {levels}. They never go away.\n"
            f"Level **{config.GIF_MIN_LEVEL}** unlocks GIFs and level **{config.IMAGE_MIN_LEVEL}** unlocks pictures. "
            f"Check yours with `{config.PREFIX}r`."
        ),
        inline=False,
    )
    embed.add_field(
        name="🌟 Prestige",
        value=(
            f"At level {config.MAX_LEVEL} use `{config.PREFIX}prestige` to restart from level {config.PRESTIGE_START_LEVEL} "
            f"and earn the next Prestige rank (up to Prestige {config.MAX_PRESTIGE}). You keep every badge."
        ),
        inline=False,
    )
    return embed


def vcinfo_embed() -> discord.Embed:
    return discord.Embed(
        title="🎧 Your own voice channel",
        description=(
            "Join **Join2Create** and a private voice channel is made for you. You are the owner.\n\n"
            "Use the buttons in your channel's chat, or type commands:\n"
            f"`{config.PREFIX}vc lock` / `unlock` · `limit 5` · `rename <name>`\n"
            f"`{config.PREFIX}vc kick @user` · `ban @user` · `unban @user`\n"
            f"`{config.PREFIX}vc permit @user` (lets them in when it's locked) · `transfer @user`\n\n"
            "When everyone leaves, the channel deletes itself. If you leave and others stay, the channel passes to one of them."
        ),
        color=discord.Color.blurple(),
    )


INFO_EMBEDS = {"rules": rules_embed, "roles": roles_embed, "vcinfo": vcinfo_embed}


class ServerLayout(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _find(guild: discord.Guild, kind: type, name: str):
        wanted = norm_name(name)
        return discord.utils.find(lambda c: isinstance(c, kind) and norm_name(c.name) == wanted, guild.channels)

    @commands.hybrid_command(
        name="setupserver",
        aliases=["setuplayout"],
        description="Admin: create the rules / announce / roles / lounge / bots / media / voice channels.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setupserver(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_channels:
            await ctx.send("I need the **Manage Channels** permission first (Server Settings → Roles → my role).", ephemeral=True)
            return
        await ctx.defer()

        read_only = {
            guild.default_role: discord.PermissionOverwrite(
                send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False
            ),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
        }
        created, existing, problems = [], [], []
        hub: discord.VoiceChannel | None = None

        for category_name, channels in LAYOUT:
            reason = f"Created by {ctx.author} with ,setupserver"
            category = self._find(guild, discord.CategoryChannel, category_name)
            if category is None:
                try:
                    category = await guild.create_category(category_name, reason=reason)
                    created.append(f"📁 {category_name}")
                except discord.HTTPException:
                    log.exception("Couldn't create category %s", category_name)
                    problems.append(f"❌ {category_name}")
                    continue
            for kind, emoji, name, topic, locked, info in channels:
                shown = f"{emoji}・{name}"
                found = self._find(guild, discord.VoiceChannel if kind == "voice" else discord.TextChannel, name)
                if found is not None:
                    existing.append(found.mention if kind == "text" else found.name)
                    if info == "hub":
                        hub = found
                    continue
                try:
                    if kind == "voice":
                        channel = await guild.create_voice_channel(shown, category=category, reason=reason)
                    else:
                        channel = await guild.create_text_channel(
                            shown, category=category, topic=topic, reason=reason,
                            overwrites=read_only if locked else discord.utils.MISSING,
                        )
                except discord.HTTPException:
                    log.exception("Couldn't create channel %s", shown)
                    problems.append(f"❌ {shown}")
                    continue
                created.append(channel.mention if kind == "text" else channel.name)
                if info == "hub":
                    hub = channel
                elif info in INFO_EMBEDS:
                    try:
                        await channel.send(embed=INFO_EMBEDS[info]())
                    except discord.HTTPException:
                        problems.append(f"⚠️ Couldn't post the text in {channel.mention}")

        lines = []
        if created:
            lines.append(f"✅ Created **{len(created)}**: " + ", ".join(created))
        if existing:
            lines.append("⏭️ Already there (left alone): " + ", ".join(existing))
        lines += problems
        privatevc = self.bot.get_cog("PrivateVC")
        if hub is not None and privatevc is not None:
            await privatevc.register_hub(guild.id, hub.id)
            lines.append(f"🎧 {hub.name} is the Join-to-Create channel. Join it to get your own private channel.")
        lines.append("Edit the rules and roles text any time. Post news in the announce channel with `,announce <text>`.")
        text = "\n".join(lines)
        await ctx.send(text[:1990] + ("…" if len(text) > 1990 else ""))

    @commands.hybrid_command(name="announce", description="Admin: post an announcement in the announce channel.")
    @app_commands.describe(message="What to announce")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def announce(self, ctx: commands.Context, *, message: str) -> None:
        channel = self._find(ctx.guild, discord.TextChannel, "announce")
        if channel is None:
            await ctx.send("There's no announce channel yet. Run `,setupserver` first.", ephemeral=True)
            return
        embed = discord.Embed(title="📢 Announcement", description=message[:4000], color=discord.Color.gold())
        embed.set_footer(text=f"Posted by {ctx.author.display_name}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            await ctx.send(f"I couldn't post in {channel.mention}. Can I send messages there?", ephemeral=True)
            return
        await ctx.send(f"✅ Posted in {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerLayout(bot))
