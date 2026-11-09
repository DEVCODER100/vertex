"""Admin tools that create roles for you: ,createroles (staff + premium tiers) and ,makerole."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.customroles import parse_color
from rolesutil import arrange_roles, find_role

log = logging.getLogger("vertex.serverroles")

NO_PERMISSIONS = discord.Permissions.none()


class ServerRoles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _create(self, guild: discord.Guild, name: str, color: int, hoist: bool, reason: str) -> discord.Role:
        # No permissions on purpose: names like "Owner" must not grant any power by themselves.
        return await guild.create_role(
            name=name,
            colour=discord.Colour(color),
            hoist=hoist,
            permissions=NO_PERMISSIONS,
            mentionable=False,
            reason=reason,
        )

    @commands.hybrid_command(
        name="createroles",
        aliases=["mkroles"],
        description="Admin: create the staff roles (Owner to Trial Moderator) and the premium tier roles.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def createroles(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        await ctx.defer()

        # A new role lands at the bottom of the list, so create from the top rank down:
        # Owner ends up highest, then the staff ranks, then Eternal down to Elite below them.
        specs = [(name, color, True) for name, color in config.SERVER_ROLES]
        specs += [(name, color, False) for name, _price, color in reversed(config.TIER_ROLES)]

        created, existing, problems = [], [], []
        for name, color, hoist in specs:
            if find_role(guild, name) is not None:
                existing.append(name)
                continue
            try:
                await self._create(guild, name, color, hoist, f"Created by {ctx.author} with ,createroles")
                created.append(name)
            except discord.HTTPException:
                log.exception("Couldn't create role %s", name)
                problems.append(f"❌ **{name}**: couldn't create it")

        lines = []
        if created:
            lines.append(f"✅ Created **{len(created)}** role(s): " + ", ".join(created))
        if existing:
            lines.append(f"⏭️ Already existed (left alone): " + ", ".join(existing))
        lines += problems
        lines.append(await self._arrange_note(guild))
        lines.append("ℹ️ These roles have **no permissions yet**. Set what each rank can do in Server Settings → Roles.")
        await ctx.send("\n".join(lines))

    async def _arrange_note(self, guild: discord.Guild) -> str:
        try:
            moved = await arrange_roles(guild)
        except discord.Forbidden:
            return "⚠️ I couldn't reorder the roles. Move my role to the top of the list, then run `,arrangeroles`."
        except discord.HTTPException:
            log.exception("Couldn't arrange roles")
            return "⚠️ Reordering the roles failed. Try `,arrangeroles` again."
        return f"🔀 Put the roles in rank order: Owner on top, then staff, tiers, Prestige 10 → 1, Level 100 → 0 ({moved} role(s) moved)."

    @commands.hybrid_command(
        name="arrangeroles",
        aliases=["arrange"],
        description="Admin: put the roles in rank order (Owner on top ... Prestige 10 to 1 ... Level 100 to 0).",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def arrangeroles(self, ctx: commands.Context) -> None:
        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        await ctx.defer()
        await ctx.send(await self._arrange_note(ctx.guild))

    @commands.hybrid_command(name="makerole", aliases=["mkrole"], description="Admin: create one role with no permissions.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def makerole(self, ctx: commands.Context, name: str, color: str = "") -> None:
        guild = ctx.guild
        name = " ".join(name.split())
        if not 1 <= len(name) <= 100:
            await ctx.send("Role names must be 1 to 100 characters.", ephemeral=True)
            return
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        if find_role(guild, name) is not None:
            await ctx.send(f"A role called **{name}** already exists.", ephemeral=True)
            return
        try:
            value = parse_color(color) if color else discord.Colour.default()
        except ValueError:
            await ctx.send("Use a hex colour like `#ff66aa`, or leave it out.", ephemeral=True)
            return
        try:
            role = await self._create(guild, name, value.value, False, f"Created by {ctx.author} with ,makerole")
        except discord.HTTPException:
            log.exception("Couldn't create role %s", name)
            await ctx.send("I couldn't create that role. Do I have Manage Roles, and is the server under 250 roles?", ephemeral=True)
            return
        await ctx.send(f"✅ Created {role.mention} with no permissions.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerRoles(bot))
