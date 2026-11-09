"""Custom roles. Owning a tier role (Elite ... Eternal) lets you create your own role:
name it, colour it, give it an icon, and share it with friends (more friends on higher tiers)."""

import difflib
import logging

import discord
from discord.ext import commands

import config
from rolesutil import arrange_roles, match_role

log = logging.getLogger("vertex.customroles")

ICON_MAX_BYTES = 256 * 1024  # Discord's limit for role icons
NO_PERMISSIONS = discord.Permissions.none()
CLEAR_WORDS = {"remove", "none", "clear", "off"}


def parse_color(text: str) -> discord.Colour:
    """Accept '#ff66aa' or 'ff66aa'. Raises ValueError otherwise."""
    cleaned = text.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError
    return discord.Colour(int(cleaned, 16))


def tier_of(member: discord.Member) -> tuple[str, int] | None:
    """The highest tier role the member owns, and how many friends it lets them share with."""
    for name, _price, _color in sorted(config.TIER_ROLES, key=lambda t: t[1], reverse=True):
        if match_role(member.roles, name) is not None:
            return name, config.TIER_FRIEND_LIMITS.get(name, 0)
    return None


class CustomRoles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---- helpers -------------------------------------------------------

    async def _own_role(self, ctx: commands.Context) -> discord.Role | None:
        """The author's custom role, cleaning up the record if the role was deleted."""
        role_id = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if role_id and role is None:
            await self.bot.db.delete_custom_role(ctx.guild.id, ctx.author.id)
        if role is None:
            await ctx.send(
                f"You don't have a custom role yet. Create one with `{config.PREFIX}cr Goat 🐐` (any name). "
                "You need a tier role: Elite, Divine, Mythic, Void or Eternal.",
                ephemeral=True,
            )
        return role

    @staticmethod
    def _validate_name(guild: discord.Guild, name: str, ignore: discord.Role | None = None) -> str | None:
        """Return an error message, or None if the name is fine."""
        if not 2 <= len(name) <= 32:
            return "Role names must be 2–32 characters."
        lowered = name.lower()
        # Names of tier and staff roles are reserved, so nobody can impersonate them.
        reserved = {t[0].lower() for t in config.TIER_ROLES} | {s[0].lower() for s in config.SERVER_ROLES}
        reserved |= {"admin", "administrator", "staff", "mod", "mods", "founder", "ceo"}
        if lowered in reserved or any(lowered.startswith(t + " ") for t in reserved) or lowered.startswith(("level ", "prestige ")):
            return "That name is reserved for a premium, staff, level or prestige role."
        if any(r.name.lower() == lowered and r != ignore for r in guild.roles):
            return "A role with that name already exists. Pick another."
        return None

    # ---- overview ------------------------------------------------------

    @commands.hybrid_group(
        name="customrole", aliases=["cr", "role", "myrole"], description="Your personal custom role.",
        fallback="info", invoke_without_command=True,
    )
    @commands.guild_only()
    async def customrole(self, ctx: commands.Context, *, name: str = "") -> None:
        p = config.PREFIX
        role_id = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        tier = tier_of(ctx.author)

        # Shortcut: ",cr Goat" creates your role named Goat (unless it looks like a typo'd sub-command).
        if name.strip():
            first = name.split()[0].lower()
            known = {n for sub in ctx.command.commands for n in (sub.name, *sub.aliases)}
            if close := difflib.get_close_matches(first, known, n=1, cutoff=0.75):
                await ctx.send(f"Did you mean `{p}cr {close[0]}`? To make a role named that, use `{p}cr make {name}`.", ephemeral=True)
                return
            if role:
                await ctx.send(f"You already have {role.mention}. Rename it with `{p}cr name {name}`.", ephemeral=True)
                return
            await ctx.invoke(self.customrole_create, name=name)
            return

        if role:
            friends = len(await self.bot.db.custom_friends(ctx.guild.id, ctx.author.id))
            limit = tier[1] if tier else 0
            text = (
                f"Your custom role is {role.mention}. Friends with it: **{friends}/{limit}**.\n"
                f"`{p}cr name <name>` · `{p}cr c #ff66aa` · `{p}cr i 🐐` · `{p}cr g @friend` · "
                f"`{p}cr rm @friend` · `{p}cr who` · `{p}cr del`"
            )
        elif tier:
            name, limit = tier
            share = f"share it with **{limit}** friend(s)" if limit else "keep it for yourself (upgrade to Divine or higher to share)"
            text = f"You own **{name}**, so you can create your own role and {share}.\nCreate it: `{p}cr Goat 🐐` (any name)"
        else:
            limits = ", ".join(f"{n} {config.TIER_FRIEND_LIMITS.get(n, 0)}" for n, _p, _c in config.TIER_ROLES)
            text = (
                "Custom roles need a **tier role** (Elite, Divine, Mythic, Void or Eternal). Buy one in the shop: "
                f"`{p}shop`.\nFriends you can share with: {limits}."
            )
        await ctx.send(text, ephemeral=True)

    # ---- create / edit -------------------------------------------------

    @customrole.command(name="create", aliases=["make", "new"], description="Create your custom role (needs a tier role).")
    async def customrole_create(self, ctx: commands.Context, *, name: str) -> None:
        db, guild, member = self.bot.db, ctx.guild, ctx.author
        name = " ".join(name.split())  # collapse whitespace/newlines

        tier = tier_of(member)
        if tier is None:
            await ctx.send(
                "You need a tier role (Elite, Divine, Mythic, Void or Eternal) to make a custom role. "
                f"Check `{config.PREFIX}shop`.",
                ephemeral=True,
            )
            return
        existing_id = await db.get_custom_role(guild.id, member.id)
        if existing_id and guild.get_role(existing_id):
            await ctx.send("You already have a custom role. Use `rename`, `color` or `icon` to change it.", ephemeral=True)
            return
        if error := self._validate_name(guild, name):
            await ctx.send(error, ephemeral=True)
            return
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission to do that.", ephemeral=True)
            return

        role = None
        try:
            role = await guild.create_role(
                name=name, permissions=NO_PERMISSIONS, hoist=False, mentionable=False,
                reason=f"Custom role for {member} ({tier[0]})",
            )
            await member.add_roles(role, reason="Created a custom role")
        except discord.HTTPException:
            log.exception("Custom role creation failed for %s", member)
            if role is not None:
                try:
                    await role.delete(reason="Custom role creation failed")
                except discord.HTTPException:
                    pass
            await ctx.send("Something went wrong creating your role. Try again.", ephemeral=True)
            return

        await db.set_custom_role(guild.id, member.id, role.id)
        try:
            await arrange_roles(guild)  # new roles start at the very bottom; slot this one in under the tiers
        except discord.HTTPException:
            log.warning("Couldn't move the new custom role into place; an admin can run ,arrangeroles")

        tier_name, limit = tier
        share = f"You can share it with **{limit}** friend(s): `{config.PREFIX}cr g @friend`." if limit else (
            "Your tier can't share it; Divine and higher can."
        )
        await ctx.send(
            f"✨ {member.mention} now has {role.mention}! Set its color: `{config.PREFIX}cr c #ff66aa` · "
            f"icon: `{config.PREFIX}cr i 🐐`. {share}"
        )

    @customrole.command(name="rename", aliases=["name"], description="Rename your custom role.")
    async def customrole_rename(self, ctx: commands.Context, *, name: str) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        name = " ".join(name.split())
        if error := self._validate_name(ctx.guild, name, ignore=role):
            await ctx.send(error, ephemeral=True)
            return
        try:
            await role.edit(name=name, reason=f"Renamed by {ctx.author}")
        except discord.HTTPException:
            await ctx.send("I couldn't rename it. Is my role above yours?", ephemeral=True)
            return
        await ctx.send(f"✅ Renamed to {role.mention}.", ephemeral=True)

    @customrole.command(name="color", aliases=["colour", "c"], description="Change your custom role's colour (hex, like #ff66aa).")
    async def customrole_color(self, ctx: commands.Context, color: str) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        try:
            colour = parse_color(color)
        except ValueError:
            await ctx.send("Use a hex colour like `#ff66aa`.", ephemeral=True)
            return
        try:
            await role.edit(colour=colour, reason=f"Recoloured by {ctx.author}")
        except discord.HTTPException:
            await ctx.send("I couldn't change the colour. Is my role above yours?", ephemeral=True)
            return
        await ctx.send(f"🎨 Updated {role.mention}.", ephemeral=True)

    @customrole.command(name="icon", aliases=["i"], description="Give your role an emoji or picture icon (server needs Boost Level 2).")
    async def customrole_icon(
        self, ctx: commands.Context, emoji: str = "", image: discord.Attachment | None = None
    ) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        if "ROLE_ICONS" not in ctx.guild.features:
            await ctx.send(
                "Discord only allows role icons on servers with **Boost Level 2**. Until then, put an emoji in the "
                f"role's name instead: `{config.PREFIX}cr name Goat 🐐`.",
                ephemeral=True,
            )
            return

        if image is not None:
            if not (image.content_type or "").startswith("image/"):
                await ctx.send("That file isn't a picture.", ephemeral=True)
                return
            if image.size > ICON_MAX_BYTES:
                await ctx.send("Role icons must be under **256 KB**. Try a smaller picture.", ephemeral=True)
                return
            icon: bytes | str | None = await image.read()
        elif emoji.strip().lower() in CLEAR_WORDS:
            icon = None
        elif emoji.strip():
            icon = emoji.strip()
        else:
            await ctx.send(
                f"Give me an emoji (`{config.PREFIX}cr i 🐐`), attach a picture, or use `remove`.", ephemeral=True
            )
            return
        try:
            await role.edit(display_icon=icon, reason=f"Icon changed by {ctx.author}")
        except discord.HTTPException:
            await ctx.send(
                "Discord rejected that icon. Use a normal emoji (not a server emoji) or a small PNG/JPG.", ephemeral=True
            )
            return
        await ctx.send("✅ Icon removed." if icon is None else f"🖼️ Updated the icon of {role.mention}.", ephemeral=True)

    @customrole.command(name="delete", aliases=["del"], description="Delete your custom role (removes it from your friends too).")
    async def customrole_delete(self, ctx: commands.Context) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        try:
            await role.delete(reason=f"Deleted by {ctx.author}")
        except discord.HTTPException:
            await ctx.send("I couldn't delete it.", ephemeral=True)
            return
        await self.bot.db.delete_custom_role(ctx.guild.id, ctx.author.id)
        await ctx.send("🗑️ Your custom role was deleted.", ephemeral=True)

    # ---- sharing with friends --------------------------------------------

    @customrole.command(name="give", aliases=["add", "g"], description="Give your custom role to a friend.")
    async def customrole_give(self, ctx: commands.Context, member: discord.Member) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        db, guild, owner = self.bot.db, ctx.guild, ctx.author

        tier = tier_of(owner)
        if tier is None:
            await ctx.send("You need a tier role (Elite, Divine, Mythic, Void or Eternal) to share your role.", ephemeral=True)
            return
        tier_name, limit = tier
        if limit == 0:
            await ctx.send(f"**{tier_name}** can't share its role. Upgrade to Divine or higher to give it to friends.", ephemeral=True)
            return
        if member.bot or member.id == owner.id:
            await ctx.send("Pick another member, not yourself or a bot.", ephemeral=True)
            return
        if role in member.roles:
            await ctx.send(f"{member.display_name} already has {role.mention}.", ephemeral=True)
            return

        friends = await db.custom_friends(guild.id, owner.id)
        if member.id not in friends and not await db.add_custom_friend(guild.id, owner.id, member.id, limit):
            await ctx.send(f"You've reached your limit of **{limit}** friends with {tier_name}. Take it back from someone with `{config.PREFIX}cr rm @friend`.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason=f"Shared by {owner}")
        except discord.HTTPException:
            await db.remove_custom_friend(guild.id, owner.id, member.id)
            await ctx.send("I couldn't give them the role. Is my role above it?", ephemeral=True)
            return
        used = len(await db.custom_friends(guild.id, owner.id))
        await ctx.send(f"🤝 {member.mention} now has {role.mention}! ({used}/{limit} friends)")

    @customrole.command(name="take", aliases=["remove", "rm"], description="Take your custom role back from a friend.")
    async def customrole_take(self, ctx: commands.Context, member: discord.Member) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        removed_row = await self.bot.db.remove_custom_friend(ctx.guild.id, ctx.author.id, member.id)
        if role not in member.roles and not removed_row:
            await ctx.send(f"{member.display_name} doesn't have your role.", ephemeral=True)
            return
        if role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Taken back by {ctx.author}")
            except discord.HTTPException:
                await ctx.send("I couldn't remove it. Is my role above it?", ephemeral=True)
                return
        await ctx.send(f"✅ {member.mention} no longer has {role.mention}.")

    @customrole.command(name="friends", aliases=["list", "who"], description="See who has your custom role.")
    async def customrole_friends(self, ctx: commands.Context) -> None:
        role = await self._own_role(ctx)
        if role is None:
            return
        friends = await self.bot.db.custom_friends(ctx.guild.id, ctx.author.id)
        tier = tier_of(ctx.author)
        limit = tier[1] if tier else 0
        names = ", ".join(f"<@{f}>" for f in friends) or "nobody yet"
        await ctx.send(
            embed=discord.Embed(
                title=f"Who has {role.name}", description=f"**{len(friends)}/{limit}** friends\n{names}",
                color=role.colour if role.colour.value else discord.Color.blurple(),
            ),
            ephemeral=True,
        )

    @customrole.command(name="leave", description="Give up a role a friend shared with you.")
    async def customrole_leave(self, ctx: commands.Context, owner: discord.Member) -> None:
        role_id = await self.bot.db.get_custom_role(ctx.guild.id, owner.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if owner.id == ctx.author.id:
            await ctx.send(f"That's your own role. Use `{config.PREFIX}customrole delete` to remove it.", ephemeral=True)
            return
        if role is None or role not in ctx.author.roles:
            await ctx.send(f"You don't have a role from {owner.display_name}.", ephemeral=True)
            return
        try:
            await ctx.author.remove_roles(role, reason="Left a shared custom role")
        except discord.HTTPException:
            await ctx.send("I couldn't remove it.", ephemeral=True)
            return
        await self.bot.db.remove_custom_friend(ctx.guild.id, owner.id, ctx.author.id)
        await ctx.send(f"👋 You gave up {role.name}.", ephemeral=True)

    # ---- cleanup -------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Don't leave orphaned roles behind when someone leaves, and free their friend slots."""
        await self.bot.db.forget_custom_friend(member.guild.id, member.id)
        role_id = await self.bot.db.get_custom_role(member.guild.id, member.id)
        if role_id is None:
            return
        role = member.guild.get_role(role_id)
        if role is not None:
            try:
                await role.delete(reason="Owner left the server")
            except discord.HTTPException:
                log.warning("Couldn't delete custom role %s of departed member", role)
        await self.bot.db.delete_custom_role(member.guild.id, member.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self.bot.db.delete_custom_role_by_role(role.guild.id, role.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CustomRoles(bot))
