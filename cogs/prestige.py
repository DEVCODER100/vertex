"""Prestige (reset at max level for a new rank) and creating the Level / Prestige badge roles."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from rolesutil import arrange_roles, find_role, full_name

log = logging.getLogger("vertex.prestige")


class PrestigeView(discord.ui.View):
    """Confirm / Cancel buttons that only the person prestiging can press."""

    def __init__(self, cog: "Prestige", member: discord.Member, next_prestige: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.member = member
        self.next_prestige = next_prestige
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This isn't your prestige.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Prestige now", emoji="🌟", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="⏳ Prestiging...", embed=None, view=None)
        db, guild = self.cog.bot.db, self.member.guild
        new = await db.prestige_up(guild.id, self.member.id)
        if new is None:
            await interaction.edit_original_response(content="You can't prestige right now.")
            return
        leveling = self.cog.bot.get_cog("Leveling")
        if leveling is not None:
            await leveling.apply_roles(self.member)
        await interaction.edit_original_response(
            content=(
                f"🌟 {self.member.mention} reached **Prestige {new}**! "
                f"Back to level {config.PRESTIGE_START_LEVEL}. Time to climb again!"
            )
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Prestige cancelled.", embed=None, view=None)

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content="⏳ Prestige timed out.", embed=None, view=None)
            except discord.HTTPException:
                pass


class Prestige(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # ---- prestige --------------------------------------------------------

    @commands.hybrid_command(
        name="prestige", aliases=["pres", "pr"], description=f"At level {config.MAX_LEVEL}: start over and earn the next Prestige rank."
    )
    async def prestige(self, ctx: commands.Context) -> None:
        row = await self.bot.db.get_user(ctx.guild.id, ctx.author.id)
        level, current = row["level"], row["prestige"]

        if current >= config.MAX_PRESTIGE:
            await ctx.send(f"🏆 You're already at **Prestige {config.MAX_PRESTIGE}**, the highest there is!", ephemeral=True)
            return
        if level < config.MAX_LEVEL:
            await ctx.send(
                f"You need **level {config.MAX_LEVEL}** to prestige. You're level {level}. Keep chatting! 💬",
                ephemeral=True,
            )
            return

        nxt = current + 1
        embed = discord.Embed(
            title=f"🌟 Prestige {nxt}?",
            description=(
                f"You'll go back to **level {config.PRESTIGE_START_LEVEL}** and earn **Prestige {nxt}**.\n"
                "You **keep every role you've earned** (all level badges and earlier prestiges), "
                "plus your coins, Credits and shop roles."
            ),
            color=discord.Color.gold(),
        )
        view = PrestigeView(self, ctx.author, nxt)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="setprestige", aliases=["setpres"], description="Admin: set a member's prestige (0-10).")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setprestige(
        self, ctx: commands.Context, member: discord.Member, prestige: commands.Range[int, 0, config.MAX_PRESTIGE]
    ) -> None:
        if member.bot:
            await ctx.send("Bots don't have prestige. 🤖", ephemeral=True)
            return
        old, new = await self.bot.db.set_prestige(ctx.guild.id, member.id, prestige)
        leveling = self.bot.get_cog("Leveling")
        if leveling is not None:
            await leveling.apply_roles(member)
        await ctx.send(f"{member.mention} is now **Prestige {new}** (was {old}).")

    # ---- creating the roles -----------------------------------------------

    @commands.hybrid_command(
        name="setupbadges",
        aliases=["badges"],
        description="Admin: create the Level and Prestige roles and give them to everyone who earned them.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setupbadges(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        await ctx.defer()

        # A new role lands at the bottom of the list. So create Prestige 10 -> 1 first and
        # Level 90 -> 0 last: that leaves Prestige on top and the highest of each on top.
        specs = [("prestige", n, name, emoji, color) for n, name, emoji, color in sorted(config.PRESTIGE_ROLES, reverse=True)]
        specs += [("level", n, name, emoji, color) for n, name, emoji, color in sorted(config.LEVEL_BADGES, reverse=True)]

        created, reused, problems = 0, 0, []
        for kind, number, name, emoji, color in specs:
            role = find_role(guild, name)
            if role is None:
                try:
                    role = await guild.create_role(
                        name=full_name(name, emoji), colour=discord.Colour(color), reason="Level/prestige role setup"
                    )
                    created += 1
                except discord.HTTPException:
                    log.exception("Couldn't create role %s", name)
                    problems.append(f"❌ **{name}**: couldn't create it")
                    continue
            elif role >= guild.me.top_role:
                problems.append(f"⚠️ **{name}**: exists but is above my role. Move my role up.")
                continue
            else:
                reused += 1
            if kind == "level":
                await self.bot.db.set_level_role(guild.id, number, role.id)
            else:
                await self.bot.db.set_prestige_role(guild.id, number, role.id)

        leveling = self.bot.get_cog("Leveling")
        checked, changed = await leveling.sync_roles(guild) if leveling else (0, 0)

        lines = [f"✅ Created **{created}** role(s), reused **{reused}** existing."]
        lines.append(f"🎖️ Updated roles for **{changed}** member(s) (checked {checked}).")
        lines += problems
        try:
            moved = await arrange_roles(guild)
            lines.append(f"🔀 Role order fixed ({moved} role(s) moved).")
        except discord.HTTPException:
            log.warning("Couldn't reorder roles after setup; run ,arrangeroles")
            lines.append("⚠️ I couldn't reorder the roles. Run `,arrangeroles` after moving my role to the top.")
        lines.append("From now on, level-ups and prestiges update roles automatically.")
        await ctx.send("\n".join(lines))

    @commands.hybrid_command(name="syncbadges", aliases=["sync"], description="Admin: fix everyone's level and prestige roles.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def syncbadges(self, ctx: commands.Context) -> None:
        leveling = self.bot.get_cog("Leveling")
        await ctx.defer()
        checked, changed = await leveling.sync_roles(ctx.guild) if leveling else (0, 0)
        if checked == 0:
            await ctx.send(f"No level roles are set up yet. Run `{config.PREFIX}setupbadges` first.")
            return
        await ctx.send(f"🎖️ Updated **{changed}** member(s) (checked {checked}).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Prestige(bot))
