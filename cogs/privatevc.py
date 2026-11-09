"""Join-to-create private voice channels.

Join the "Join2Create" voice channel and the bot makes you a private voice channel and moves you into it.
You own it: lock / unlock it, set a member limit, rename it, kick or ban people, let specific people in, or
hand it to someone else. Use the buttons posted in the channel's chat, or the `,vc` commands. The channel
deletes itself when everyone has left.
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("vertex.privatevc")

CREATE_COOLDOWN = 8  # seconds between channels made by the same person (stops join/leave spam)
MAX_LIMIT = 99


class VcError(Exception):
    """A problem to tell the user about in plain words."""


def default_name(member: discord.Member) -> str:
    return f"🎧・{member.display_name}'s VC"[:100]


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())[:100]
    if not name:
        raise VcError("Give the channel a name.")
    return name


class ValueModal(discord.ui.Modal):
    def __init__(self, cog: "PrivateVC", action: str, title: str, label: str, placeholder: str, max_length: int) -> None:
        super().__init__(title=title)
        self.cog, self.action = cog, action
        self.field = discord.ui.TextInput(label=label, placeholder=placeholder, max_length=max_length, required=True)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.interact(interaction, self.action, value=self.field.value)


class PickView(discord.ui.View):
    """A one-person picker shown (privately) after pressing Kick / Ban / Unban / Permit / Transfer."""

    def __init__(self, cog: "PrivateVC", action: str, placeholder: str) -> None:
        super().__init__(timeout=60)
        self.cog, self.action = cog, action
        self.select = discord.ui.UserSelect(placeholder=placeholder, min_values=1, max_values=1)
        self.select.callback = self.picked
        self.add_item(self.select)

    async def picked(self, interaction: discord.Interaction) -> None:
        target = interaction.guild.get_member(self.select.values[0].id) if interaction.guild else None
        try:
            if target is None:
                raise VcError("I can't find that person in the server.")
            message = await self.cog.run(self.action, interaction.channel, interaction.user, target=target)
        except VcError as error:
            message = str(error)
        await interaction.response.edit_message(content=message, view=None)


class ControlPanel(discord.ui.View):
    """The buttons posted in every private channel. Persistent: they keep working after a bot restart."""

    def __init__(self, cog: "PrivateVC") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _modal(self, interaction: discord.Interaction, action: str, title: str, label: str, placeholder: str, max_length: int) -> None:
        if (problem := self.cog.precheck(interaction.channel, interaction.user)) is not None:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        await interaction.response.send_modal(ValueModal(self.cog, action, title, label, placeholder, max_length))

    async def _pick(self, interaction: discord.Interaction, action: str, placeholder: str) -> None:
        if (problem := self.cog.precheck(interaction.channel, interaction.user)) is not None:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        await interaction.response.send_message(placeholder, view=PickView(self.cog, action, placeholder), ephemeral=True)

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="vtx_vc:lock", row=0)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.interact(interaction, "lock")

    @discord.ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary, custom_id="vtx_vc:unlock", row=0)
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.interact(interaction, "unlock")

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="vtx_vc:limit", row=0)
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._modal(interaction, "limit", "Member limit", "Max people (0 = no limit)", "0 to 99", 2)

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="vtx_vc:rename", row=0)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._modal(interaction, "rename", "Rename your channel", "New name", "My cool channel", 100)

    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger, custom_id="vtx_vc:kick", row=1)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "kick", "Who do you want to kick out?")

    @discord.ui.button(label="Ban", emoji="⛔", style=discord.ButtonStyle.danger, custom_id="vtx_vc:ban", row=1)
    async def ban(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "ban", "Who do you want to ban from this channel?")

    @discord.ui.button(label="Unban", emoji="♻️", style=discord.ButtonStyle.secondary, custom_id="vtx_vc:unban", row=1)
    async def unban(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "unban", "Who do you want to unban?")

    @discord.ui.button(label="Permit", emoji="✅", style=discord.ButtonStyle.success, custom_id="vtx_vc:permit", row=1)
    async def permit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "permit", "Who may join (even when locked)?")

    @discord.ui.button(label="Transfer", emoji="👑", style=discord.ButtonStyle.primary, custom_id="vtx_vc:transfer", row=1)
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "transfer", "Who should own the channel now?")


def panel_embed(owner: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🎧 Your private voice channel",
        description=(
            f"{owner.mention} owns this channel. Only the owner can use the buttons below.\n\n"
            "🔒 **Lock** / 🔓 **Unlock**: stop or allow new people joining\n"
            "👥 **Limit**: how many people can be in here\n"
            "✏️ **Rename**: change the channel's name\n"
            "👢 **Kick**: remove someone from the call\n"
            "⛔ **Ban** / ♻️ **Unban**: keep someone out for good (or let them back)\n"
            "✅ **Permit**: let someone join even when it's locked\n"
            "👑 **Transfer**: give the channel to someone else\n\n"
            f"Prefer typing? `{config.PREFIX}vc lock`, `{config.PREFIX}vc kick @user` and so on. "
            f"`{config.PREFIX}vc` shows them all. The channel deletes itself when it's empty."
        ),
        color=discord.Color.blurple(),
    )
    return embed


class PrivateVC(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.hubs: set[int] = set()
        self.owners: dict[int, int] = {}  # private channel id -> owner's user id
        self.last_created: dict[int, float] = {}
        self._cleaned = False

    async def cog_load(self) -> None:
        self.hubs = {row["channel_id"] for row in await self.bot.db.all_vc_hubs()}
        self.owners = {row["channel_id"]: row["owner_id"] for row in await self.bot.db.all_temp_vcs()}
        self.bot.add_view(ControlPanel(self))

    # ---- setup helpers -----------------------------------------------------

    async def register_hub(self, guild_id: int, channel_id: int) -> None:
        await self.bot.db.add_vc_hub(guild_id, channel_id)
        self.hubs.add(channel_id)

    @commands.hybrid_command(name="sethub", description="Admin: make an existing voice channel the Join-to-Create channel.")
    @app_commands.describe(channel="The voice channel people join to get their own channel")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def sethub(self, ctx: commands.Context, channel: discord.VoiceChannel) -> None:
        await self.register_hub(ctx.guild.id, channel.id)
        await ctx.send(f"✅ {channel.mention} is now the Join-to-Create channel.", ephemeral=True)

    # ---- the join / leave logic --------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """After a restart: forget channels that are gone and delete private channels nobody is in."""
        if self._cleaned:
            return
        self._cleaned = True
        for channel_id in list(self.owners):
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                await self._forget(channel_id)
            elif not channel.members:
                await self._delete(channel)
        for hub_id in list(self.hubs):
            if self.bot.get_channel(hub_id) is None:
                self.hubs.discard(hub_id)
                await self.bot.db.remove_vc_hub(hub_id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        if before.channel is not None and before.channel.id in self.owners:
            await self._after_leave(before.channel)
        if after.channel is not None and after.channel.id in self.hubs and not member.bot:
            await self._create_for(member, after.channel)

    async def _forget(self, channel_id: int) -> None:
        self.owners.pop(channel_id, None)
        await self.bot.db.remove_temp_vc(channel_id)

    async def _delete(self, channel: discord.VoiceChannel) -> None:
        await self._forget(channel.id)
        try:
            await channel.delete(reason="Private voice channel is empty")
        except discord.HTTPException:
            log.warning("Couldn't delete private voice channel %s", channel.id)

    async def _after_leave(self, channel: discord.VoiceChannel) -> None:
        humans = [m for m in channel.members if not m.bot]
        if not humans:
            await self._delete(channel)
            return
        owner_id = self.owners.get(channel.id)
        if owner_id in {m.id for m in humans}:
            return
        # The owner left but people are still in here: hand the channel to someone who stayed.
        new_owner = humans[0]
        try:
            await self._give_ownership(channel, new_owner)
            await channel.send(f"👑 The owner left, so {new_owner.mention} owns this channel now.")
        except discord.HTTPException:
            log.warning("Couldn't hand over private voice channel %s", channel.id)

    async def _give_ownership(self, channel: discord.VoiceChannel, new_owner: discord.Member) -> None:
        old_owner = channel.guild.get_member(self.owners.get(channel.id, 0))
        await channel.set_permissions(new_owner, connect=True, view_channel=True)
        if old_owner is not None and old_owner.id != new_owner.id:
            await channel.set_permissions(old_owner, overwrite=None)
        self.owners[channel.id] = new_owner.id
        await self.bot.db.set_temp_vc_owner(channel.id, new_owner.id)

    async def _create_for(self, member: discord.Member, hub: discord.VoiceChannel) -> None:
        now = time.monotonic()
        if now - self.last_created.get(member.id, 0.0) < CREATE_COOLDOWN:
            try:
                await member.move_to(None, reason="Creating voice channels too fast")
            except discord.HTTPException:
                pass
            return
        self.last_created[member.id] = now

        overwrites = dict(hub.category.overwrites) if hub.category else {}
        overwrites[member] = discord.PermissionOverwrite(connect=True, view_channel=True)
        overwrites[hub.guild.me] = discord.PermissionOverwrite(
            connect=True, view_channel=True, manage_channels=True, move_members=True, send_messages=True, embed_links=True
        )
        try:
            channel = await hub.guild.create_voice_channel(
                name=default_name(member), category=hub.category, overwrites=overwrites, reason=f"Join-to-create for {member}"
            )
        except discord.HTTPException:
            log.exception("Couldn't create a private voice channel for %s", member)
            try:
                await member.move_to(None)
            except discord.HTTPException:
                pass
            return

        self.owners[channel.id] = member.id
        await self.bot.db.add_temp_vc(hub.guild.id, channel.id, member.id)
        try:
            await member.move_to(channel, reason="Join-to-create")
        except discord.HTTPException:
            await self._delete(channel)  # they left before we could move them
            return
        try:
            await channel.send(content=member.mention, embed=panel_embed(member), view=ControlPanel(self))
        except discord.HTTPException:
            log.warning("Couldn't post the control panel in %s", channel.id)

    # ---- owner actions -----------------------------------------------------

    def precheck(self, channel, actor: discord.abc.User) -> str | None:
        """None if `actor` may control `channel`, otherwise a message explaining why not."""
        if not isinstance(channel, discord.VoiceChannel) or channel.id not in self.owners:
            return "That isn't a private voice channel made with Join2Create."
        owner_id = self.owners[channel.id]
        if owner_id != actor.id:
            return f"Only the owner (<@{owner_id}>) can do that."
        return None

    async def run(self, action: str, channel, actor: discord.Member, *, target: discord.Member | None = None, value: str = "") -> str:
        if (problem := self.precheck(channel, actor)) is not None:
            raise VcError(problem)
        try:
            return await getattr(self, f"_do_{action}")(channel, actor, target, value)
        except discord.Forbidden:
            raise VcError("I'm missing a permission for that. Ask an admin to give me Manage Channels and Move Members.") from None
        except discord.HTTPException:
            log.exception("Voice action %s failed", action)
            raise VcError("Discord refused that. Try again in a moment.") from None

    def _check_target(self, channel: discord.VoiceChannel, actor: discord.Member, target: discord.Member | None) -> discord.Member:
        if target is None:
            raise VcError("Pick a person.")
        if target.id == actor.id:
            raise VcError("You can't do that to yourself.")
        if target.bot:
            raise VcError("That won't work on bots.")
        return target

    @staticmethod
    def _in_channel(channel: discord.VoiceChannel, target: discord.Member) -> bool:
        return target.voice is not None and target.voice.channel == channel

    async def _do_lock(self, channel, actor, target, value) -> str:
        await channel.set_permissions(channel.guild.default_role, connect=False)
        return "🔒 Locked. Only you and people you permit can join."

    async def _do_unlock(self, channel, actor, target, value) -> str:
        await channel.set_permissions(channel.guild.default_role, connect=None)
        return "🔓 Unlocked. Anyone can join again."

    async def _do_limit(self, channel, actor, target, value) -> str:
        try:
            number = int(value.strip())
        except ValueError:
            raise VcError("Type a number from 0 to 99 (0 = no limit).") from None
        if not 0 <= number <= MAX_LIMIT:
            raise VcError("The limit must be from 0 to 99 (0 = no limit).")
        await channel.edit(user_limit=number)
        return "👥 No member limit." if number == 0 else f"👥 Limit set to **{number}**."

    async def _do_rename(self, channel, actor, target, value) -> str:
        name = clean_name(value)
        await channel.edit(name=name)
        return f"✏️ Renamed to **{name}**."

    async def _do_kick(self, channel, actor, target, value) -> str:
        target = self._check_target(channel, actor, target)
        if not self._in_channel(channel, target):
            raise VcError(f"{target.display_name} isn't in your channel.")
        await target.move_to(None, reason=f"Kicked from their private channel by {actor}")
        return f"👢 Kicked {target.mention}. They can rejoin unless you ban them."

    async def _do_ban(self, channel, actor, target, value) -> str:
        target = self._check_target(channel, actor, target)
        await channel.set_permissions(target, connect=False)
        if self._in_channel(channel, target):
            await target.move_to(None, reason=f"Banned from their private channel by {actor}")
        return f"⛔ {target.mention} is banned from this channel."

    async def _do_unban(self, channel, actor, target, value) -> str:
        target = self._check_target(channel, actor, target)
        await channel.set_permissions(target, overwrite=None)
        return f"♻️ {target.mention} can join again."

    async def _do_permit(self, channel, actor, target, value) -> str:
        target = self._check_target(channel, actor, target)
        await channel.set_permissions(target, connect=True, view_channel=True)
        return f"✅ {target.mention} can join, even when it's locked."

    async def _do_transfer(self, channel, actor, target, value) -> str:
        target = self._check_target(channel, actor, target)
        if not self._in_channel(channel, target):
            raise VcError(f"{target.display_name} has to be in the channel to get it.")
        await self._give_ownership(channel, target)
        return f"👑 {target.mention} owns the channel now."

    async def interact(self, interaction: discord.Interaction, action: str, **kwargs) -> None:
        try:
            message = await self.run(action, interaction.channel, interaction.user, **kwargs)
        except VcError as error:
            message = str(error)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ---- ,vc commands ------------------------------------------------------

    async def _command(self, ctx: commands.Context, action: str, **kwargs) -> None:
        voice = ctx.author.voice
        try:
            if voice is None or voice.channel is None:
                raise VcError("Join your private voice channel first.")
            message = await self.run(action, voice.channel, ctx.author, **kwargs)
        except VcError as error:
            message = str(error)
        await ctx.send(message, ephemeral=True)

    @commands.hybrid_group(name="vc", aliases=["voice"], fallback="help", description="Control your private voice channel.", invoke_without_command=True)
    @commands.guild_only()
    async def vc(self, ctx: commands.Context) -> None:
        p = config.PREFIX
        await ctx.send(
            "**Your private voice channel** (join **Join2Create** to get one)\n"
            f"`{p}vc lock` / `{p}vc unlock` · `{p}vc limit 5` · `{p}vc rename name`\n"
            f"`{p}vc kick @user` · `{p}vc ban @user` · `{p}vc unban @user`\n"
            f"`{p}vc permit @user` (can join when locked) · `{p}vc transfer @user`\n"
            "Or use the buttons in your channel's chat.",
            ephemeral=True,
        )

    @vc.command(name="lock", description="Stop new people joining your channel.")
    async def vc_lock(self, ctx: commands.Context) -> None:
        await self._command(ctx, "lock")

    @vc.command(name="unlock", description="Let anyone join your channel again.")
    async def vc_unlock(self, ctx: commands.Context) -> None:
        await self._command(ctx, "unlock")

    @vc.command(name="limit", aliases=["max"], description="Set how many people can be in your channel (0 = no limit).")
    @app_commands.describe(number="0 to 99")
    async def vc_limit(self, ctx: commands.Context, number: int) -> None:
        await self._command(ctx, "limit", value=str(number))

    @vc.command(name="rename", aliases=["name"], description="Rename your channel.")
    async def vc_rename(self, ctx: commands.Context, *, name: str) -> None:
        await self._command(ctx, "rename", value=name)

    @vc.command(name="kick", description="Remove someone from your channel.")
    async def vc_kick(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._command(ctx, "kick", target=member)

    @vc.command(name="ban", description="Keep someone out of your channel.")
    async def vc_ban(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._command(ctx, "ban", target=member)

    @vc.command(name="unban", description="Let a banned person back in.")
    async def vc_unban(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._command(ctx, "unban", target=member)

    @vc.command(name="permit", aliases=["allow", "invite"], description="Let someone join even when your channel is locked.")
    async def vc_permit(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._command(ctx, "permit", target=member)

    @vc.command(name="transfer", description="Give your channel to someone in it.")
    async def vc_transfer(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._command(ctx, "transfer", target=member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrivateVC(bot))
