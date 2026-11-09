"""XP from chatting, level-up messages, level/prestige roles, and the rank card."""

import asyncio
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import levels
from rolesutil import norm_name

log = logging.getLogger("vertex.leveling")


def _bar(done: int, total: int, width: int = 12) -> str:
    filled = round(width * done / total) if total else 0
    return "▰" * filled + "▱" * (width - filled)


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_award: dict[tuple[int, int], float] = {}

    # ---- earning XP ----------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if now - self._last_award.get(key, -1e9) < config.XP_COOLDOWN_SECONDS:
            return
        self._last_award[key] = now

        await self.award_xp(message.channel, message.author, random.randint(config.XP_MIN, config.XP_MAX))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Give newcomers (and returning members) the roles that match their level."""
        if not member.bot:
            await self.apply_roles(member)

    async def award_xp(self, channel: discord.abc.Messageable, member: discord.Member, amount: int) -> None:
        """Give XP from any source (chatting, quizzes...) with level-up message and role rewards."""
        old_level, new_level, _ = await self.bot.db.add_xp(member.guild.id, member.id, amount)
        if new_level > old_level:
            await self.announce_level_up(channel, member, new_level)

    async def announce_level_up(self, channel: discord.abc.Messageable, member: discord.Member, new_level: int) -> None:
        text = f"🎉 {member.mention} reached **level {new_level}**!"

        added, _ = await self.apply_roles(member)
        if added:
            text += "\nUnlocked: " + ", ".join(role.mention for role in added)
        if new_level >= config.MAX_LEVEL:
            row = await self.bot.db.get_user(member.guild.id, member.id)
            if row["prestige"] < config.MAX_PRESTIGE:
                text += f"\n🌟 Max level! Run `{config.PREFIX}prestige` to start over and earn the next Prestige rank."

        # If the server has a #levels channel (made by ,setupserver), level-ups go there.
        target = channel
        for candidate in member.guild.text_channels:
            if norm_name(candidate.name) == "levels" and candidate.permissions_for(member.guild.me).send_messages:
                target = candidate
                break
        try:
            await target.send(text)
        except discord.HTTPException:
            log.warning("Couldn't send level-up message in %s", target)

    # ---- level + prestige roles --------------------------------------------

    async def apply_roles(self, member: discord.Member, row=None) -> tuple[list[discord.Role], list[discord.Role]]:
        """Make the member's level badge and prestige role match their progress.
        Returns (roles added, roles removed). `row` may carry the member's level/prestige."""
        db, guild = self.bot.db, member.guild
        if row is None:
            row = await db.get_user(guild.id, member.id)
        level, prestige = row["level"], row["prestige"]

        level_rows = await db.level_roles(guild.id)
        prestige_rows = await db.prestige_roles(guild.id)

        # Anyone who has prestiged has already finished level 100 at least once, so they keep every badge.
        badge_level = levels.effective_level(level, prestige)
        eligible = [r for r in level_rows if r["level"] <= badge_level]
        if not config.STACK_LEVEL_ROLES and eligible:
            eligible = [max(eligible, key=lambda r: r["level"])]  # only the best badge
        target = {r["role_id"] for r in eligible}
        if config.STACK_PRESTIGE_ROLES:
            target |= {r["role_id"] for r in prestige_rows if r["prestige"] <= prestige}
        else:
            target |= {r["role_id"] for r in prestige_rows if r["prestige"] == prestige}
        managed = {r["role_id"] for r in level_rows} | {r["role_id"] for r in prestige_rows}

        have = {role.id for role in member.roles}
        to_add = [role for role in (guild.get_role(i) for i in target - have) if role is not None]
        to_remove = [role for role in member.roles if role.id in managed and role.id not in target]
        if not to_add and not to_remove:
            return [], []

        added, removed = [], []
        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason=f"Level {level} / prestige {prestige}")
                removed = to_remove
            if to_add:
                await member.add_roles(*to_add, reason=f"Level {level} / prestige {prestige}")
                added = to_add
        except discord.Forbidden:
            log.warning("Can't change roles for %s. Move my role above the level roles and grant Manage Roles.", member)
        except discord.HTTPException:
            log.exception("Failed to update level roles for %s", member)
        return added, removed

    async def sync_roles(self, guild: discord.Guild) -> tuple[int, int]:
        """Fix everyone's level and prestige roles (e.g. right after the roles are created).
        Returns (members checked, members whose roles changed)."""
        if not await self.bot.db.level_roles(guild.id) and not await self.bot.db.prestige_roles(guild.id):
            return 0, 0
        progress = await self.bot.db.all_levels(guild.id)
        blank = {"level": 0, "prestige": 0}
        checked = changed = 0
        for member in list(guild.members):
            if member.bot:
                continue
            checked += 1
            added, removed = await self.apply_roles(member, progress.get(member.id, blank))
            if added or removed:
                changed += 1
                await asyncio.sleep(0.3)  # stay well inside Discord's rate limits
        return checked, changed

    # ---- commands ------------------------------------------------------

    @commands.hybrid_command(name="rank", aliases=["r", "lvl", "level", "xp"], description="Show your level and XP.")
    @commands.guild_only()
    async def rank(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        member = member or ctx.author
        row = await self.bot.db.get_user(ctx.guild.id, member.id)
        level, into, needed = levels.progress(row["xp"])
        position = await self.bot.db.rank_of(ctx.guild.id, member.id, "xp")

        embed = discord.Embed(title=member.display_name, color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="Rank", value=f"#{position}")
        if row["prestige"]:
            embed.add_field(name="Prestige", value=f"⭐ {row['prestige']}")
        embed.add_field(name="Total XP", value=f"{row['xp']:,}")

        if level >= config.MAX_LEVEL:
            if row["prestige"] >= config.MAX_PRESTIGE:
                progress = "🏆 **Max level and max prestige!**"
            else:
                progress = f"🌟 **Max level!** Run `{config.PREFIX}prestige` to earn Prestige {row['prestige'] + 1}."
            embed.add_field(name="Progress", value=progress, inline=False)
        else:
            embed.add_field(
                name=f"Progress to level {level + 1}",
                value=f"{_bar(into, needed)}  `{into:,} / {needed:,} XP`",
                inline=False,
            )
        await ctx.send(embed=embed)

    # ---- admin: change someone's level -----------------------------------

    async def _change_level(self, ctx: commands.Context, member: discord.Member, new_level: int) -> None:
        if member.bot:
            await ctx.send("Bots don't have levels. 🤖", ephemeral=True)
            return
        old_level, new_level = await self.bot.db.set_level(ctx.guild.id, member.id, new_level)
        if new_level > old_level:
            await ctx.send(f"⬆️ {member.mention} is now **level {new_level}** (was {old_level}).")
            await self.announce_level_up(ctx.channel, member, new_level)  # level-up message + roles
        else:
            await ctx.send(f"{member.mention} is now **level {new_level}** (was {old_level}).")
            await self.apply_roles(member)  # lowering a level also fixes their badge

    @commands.hybrid_command(name="setlevel", aliases=["setlvl"], description="Admin: set a member's level exactly.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setlevel(
        self, ctx: commands.Context, member: discord.Member, level: commands.Range[int, 0, config.MAX_LEVEL]
    ) -> None:
        await self._change_level(ctx, member, level)

    @commands.hybrid_command(name="addlevel", aliases=["addlvl"], description="Admin: raise a member's level by some amount.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def addlevel(
        self, ctx: commands.Context, member: discord.Member, amount: commands.Range[int, 1, config.MAX_LEVEL]
    ) -> None:
        current = (await self.bot.db.get_user(ctx.guild.id, member.id))["level"]
        await self._change_level(ctx, member, min(current + amount, config.MAX_LEVEL))

    # ---- custom level rewards ------------------------------------------------

    @commands.hybrid_group(name="levelrole", aliases=["lr"], description="Manage level role rewards.", invoke_without_command=True)
    @commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def levelrole(self, ctx: commands.Context) -> None:
        await ctx.invoke(self.levelrole_list)

    @levelrole.command(name="add", description="Give a role to members who reach a level.")
    @commands.has_permissions(manage_guild=True)
    async def levelrole_add(
        self, ctx: commands.Context, level: commands.Range[int, 0, config.MAX_LEVEL], role: discord.Role
    ) -> None:
        if role >= ctx.guild.me.top_role:
            await ctx.send("I can only hand out roles that sit **below my own highest role**. Move mine up first.", ephemeral=True)
            return
        await self.bot.db.set_level_role(ctx.guild.id, level, role.id)
        await ctx.send(f"✅ Members reaching **level {level}** will now get {role.mention}.", ephemeral=True)

    @levelrole.command(name="remove", description="Stop rewarding a level with a role.")
    @commands.has_permissions(manage_guild=True)
    async def levelrole_remove(self, ctx: commands.Context, level: commands.Range[int, 0, config.MAX_LEVEL]) -> None:
        removed = await self.bot.db.remove_level_role(ctx.guild.id, level)
        await ctx.send("✅ Removed." if removed else "There's no reward set for that level.", ephemeral=True)

    @levelrole.command(name="list", description="Show all level role rewards.")
    async def levelrole_list(self, ctx: commands.Context) -> None:
        rows = await self.bot.db.level_roles(ctx.guild.id)
        if not rows:
            await ctx.send(f"No level roles yet. Run `{config.PREFIX}setupbadges`, or add one with `{config.PREFIX}levelrole add 5 @Role`.", ephemeral=True)
            return
        lines = [f"**Level {r['level']}** → <@&{r['role_id']}>" for r in rows]
        await ctx.send(embed=discord.Embed(title="Level roles", description="\n".join(lines), color=discord.Color.blurple()))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leveling(bot))
