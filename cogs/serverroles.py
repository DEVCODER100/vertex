"""Admin tools that create roles for you: ,createroles (staff + premium tiers) and ,makerole."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.customroles import parse_color
from rolesutil import arrange_roles, find_role, upper_rank_names

log = logging.getLogger("vertex.serverroles")

NO_PERMISSIONS = discord.Permissions.none()
BOTS_ROLE_NAME = "Bots"
BOTS_ROLE_COLOR = 0x5865F2


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

    @commands.hybrid_command(
        name="hoistroles",
        aliases=["groups", "hoist"],
        description="Admin: show the ranks as separate groups in the member list (Owner on top ... down to Level 5).",
    )
    @app_commands.describe(from_level="Lowest level badge that gets its own group (default 5)")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def hoistroles(self, ctx: commands.Context, from_level: int = 5) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        await ctx.defer()

        wanted: dict[discord.Role, bool] = {}
        for name in upper_rank_names():
            if (role := find_role(guild, name)) is not None:
                wanted[role] = True
        for number, name, *_rest in sorted(config.PRESTIGE_ROLES, reverse=True):
            if (role := find_role(guild, name)) is not None:
                wanted[role] = True
        for badge in config.LEVEL_BADGES:
            if (role := find_role(guild, badge[1])) is not None:
                wanted[role] = badge[0] >= from_level

        top = guild.me.top_role
        changed, skipped = 0, []
        for role, hoist in wanted.items():
            if role.hoist == hoist:
                continue
            if role.position >= top.position:
                skipped.append(role.name)
                continue
            try:
                await role.edit(hoist=hoist, reason=f"Member-list groups by {ctx.author} (,hoistroles)")
                changed += 1
            except discord.HTTPException:
                log.exception("Couldn't edit role %s", role.name)
                skipped.append(role.name)

        lines = [f"✅ Member-list groups updated ({changed} role(s) changed, {len(wanted)} checked)."]
        lines.append(
            f"Owner is on top, then the other staff, tiers, Prestige 10 → 1, then Level 100 → Level {from_level}. "
            f"Levels below {from_level} stay in the normal Online list."
        )
        if skipped:
            lines.append("⚠️ Couldn't change: " + ", ".join(skipped) + ". Move my role above them (Server Settings → Roles), then run this again.")
        if not wanted:
            lines.append("I found none of the rank roles. Run `,createroles` and `,setupbadges` first.")
        await ctx.send("\n".join(lines))

    async def _give_bots_role(self, guild: discord.Guild, role: discord.Role, reason: str) -> tuple[int, list[str]]:
        added, failed = 0, []
        for member in guild.members:
            if not member.bot or role in member.roles:
                continue
            try:
                await member.add_roles(role, reason=reason)
                added += 1
            except discord.HTTPException:
                failed.append(member.display_name)
        return added, failed

    @commands.hybrid_command(
        name="botsrole",
        aliases=["setupbots", "botsgroup"],
        description="Admin: give every bot a 'Bots' role so they get their own section in the member list.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def botsrole(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        await ctx.defer()
        role = find_role(guild, BOTS_ROLE_NAME)
        lines = []
        if role is None:
            try:
                role = await self._create(guild, BOTS_ROLE_NAME, BOTS_ROLE_COLOR, True, f"Created by {ctx.author} with ,botsrole")
            except discord.HTTPException:
                log.exception("Couldn't create the Bots role")
                await ctx.send("I couldn't create the **Bots** role. Do I have Manage Roles?", ephemeral=True)
                return
            lines.append(f"✅ Created the {role.mention} role (shown as its own group, no permissions).")
        else:
            if not role.hoist and role.position < guild.me.top_role.position:
                try:
                    await role.edit(hoist=True, reason="Bots get their own member-list group")
                except discord.HTTPException:
                    log.exception("Couldn't hoist the Bots role")
            lines.append(f"⏭️ The {role.mention} role already exists.")
        if role.position >= guild.me.top_role.position:
            await ctx.send("\n".join(lines + ["⚠️ My role is below **Bots**. Move my role above it (Server Settings → Roles), then run this again."]))
            return

        added, failed = await self._give_bots_role(guild, role, f"Given by {ctx.author} with ,botsrole")
        lines.append(f"🤖 Gave it to **{added}** bot(s). New bots that join get it automatically.")
        if failed:
            lines.append("⚠️ Couldn't give it to: " + ", ".join(failed) + " (their top role is above mine).")
        lines.append(await self._arrange_note(guild))
        await ctx.send("\n".join(lines))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            return
        role = find_role(member.guild, BOTS_ROLE_NAME)
        if role is None or role.position >= member.guild.me.top_role.position:
            return
        try:
            await member.add_roles(role, reason="New bot: Bots group")
        except discord.HTTPException:
            log.warning("Couldn't give the Bots role to %s", member)

    @commands.hybrid_command(
        name="lockeveryone",
        aliases=["lockping", "pingperms"],
        description="Admin: only Owner, Co-Owner and Manager can use @everyone and @here.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def lockeveryone(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return
        await ctx.defer()

        top = guild.me.top_role
        allowed = [role for name in config.PING_ROLES if (role := find_role(guild, name)) is not None]
        missing = [name for name in config.PING_ROLES if find_role(guild, name) is None]
        granted, removed, already, blocked, admins = [], [], [], [], []

        async def set_perm(role: discord.Role, value: bool) -> bool:
            if role.position >= top.position:
                blocked.append(role.name)
                return False
            perms = discord.Permissions(role.permissions.value)
            perms.mention_everyone = value
            try:
                await role.edit(permissions=perms, reason=f"Ping control by {ctx.author} (,lockeveryone)")
            except discord.HTTPException:
                log.exception("Couldn't edit mention_everyone on %s", role.name)
                blocked.append(role.name)
                return False
            return True

        # 1) everyone else: switch it off
        for role in guild.roles:
            if role in allowed:
                continue
            if role.permissions.administrator:
                admins.append(role.name)  # Administrator always includes it; it can't be limited
                continue
            if not role.permissions.mention_everyone:
                continue
            if role.managed and not role.is_default():
                blocked.append(role.name)  # a bot's own role: leave it alone
            elif await set_perm(role, False):
                removed.append("everyone" if role.is_default() else role.name)
        # 2) the three staff roles: switch it on
        for role in allowed:
            if role.permissions.mention_everyone or role.permissions.administrator:
                already.append(role.name)
            elif await set_perm(role, True):
                granted.append(role.name)

        lines = ["🔒 **@everyone / @here control**"]
        if granted:
            lines.append("✅ Can now ping everyone: " + ", ".join(granted))
        if already:
            lines.append("✔️ Already could: " + ", ".join(already))
        if removed:
            lines.append("🚫 Removed the permission from: " + ", ".join(removed))
        if not (granted or removed):
            lines.append("Nothing needed changing.")
        if missing:
            lines.append("⚠️ These roles don't exist yet: " + ", ".join(missing) + ". Run `,createroles`, then this again.")
        if blocked:
            lines.append(
                "⚠️ I couldn't change: " + ", ".join(blocked) + ". Move my role above them, and make sure my role has the "
                "**Mention Everyone** permission (I can only give out what I have). Or do it by hand: Server Settings → Roles → "
                "pick the role → turn **Mention @everyone, @here, and All Roles** on or off."
            )
        if admins:
            lines.append(
                "👑 These roles have **Administrator**, which always allows pinging everyone and can't be limited: "
                + ", ".join(admins) + ". The server owner can always ping too."
            )
        text = "\n".join(lines)
        await ctx.send(text[:1990] + ("…" if len(text) > 1990 else ""))

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
