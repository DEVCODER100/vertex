"""Marriage and adoption: ,marry @user  ,adopt @user  ,family  ,divorce  ,disown  ,runaway"""

import logging
from collections.abc import Awaitable, Callable

import discord
from discord.ext import commands

import config

log = logging.getLogger("vertex.relationships")


class ProposalView(discord.ui.View):
    """Accept/Decline buttons that only the person being asked can press."""

    def __init__(
        self,
        target: discord.Member,
        on_accept: Callable[[], Awaitable[str]],
        *,
        accept_label: str,
        accept_emoji: str,
        decline_text: str,
        timeout_text: str,
    ) -> None:
        super().__init__(timeout=config.PROPOSAL_TIMEOUT_SECONDS)
        self.target = target
        self._on_accept = on_accept
        self._decline_text = decline_text
        self._timeout_text = timeout_text
        self.message: discord.Message | None = None
        self.accept.label = accept_label
        self.accept.emoji = accept_emoji

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("This question isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        text = await self._on_accept()
        await interaction.response.edit_message(content=text, view=None)

    @discord.ui.button(label="Decline", emoji="✖️", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content=self._decline_text, view=None)

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content=self._timeout_text, view=None)
            except discord.HTTPException:
                pass


class Relationships(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # ---- family-tree helpers ------------------------------------------

    async def _ancestors(self, guild_id: int, user_id: int) -> list[int]:
        """Parent, grandparent, ... (capped, so a corrupted loop can't hang the bot)."""
        chain: list[int] = []
        current = user_id
        for _ in range(25):
            parent = await self.bot.db.get_parent(guild_id, current)
            if parent is None or parent in chain:
                break
            chain.append(parent)
            current = parent
        return chain

    async def _marriage_problem(self, guild: discord.Guild, a: discord.Member, b: discord.Member) -> str | None:
        db = self.bot.db
        if b.bot:
            return "Bots can't get married. 🤖"
        if a.id == b.id:
            return "You can't marry yourself."
        if mine := await db.get_marriage(guild.id, a.id):
            return f"You're already married to <@{mine['partner_id']}>. Use `{config.PREFIX}divorce` first."
        if await db.get_marriage(guild.id, b.id):
            return f"{b.display_name} is already married."
        if b.id in await self._ancestors(guild.id, a.id) or a.id in await self._ancestors(guild.id, b.id):
            return "You can't marry your own family!"
        parent_a, parent_b = await db.get_parent(guild.id, a.id), await db.get_parent(guild.id, b.id)
        if parent_a is not None and parent_a == parent_b:
            return "You two are siblings. You can't marry!"
        return None

    async def _adoption_problem(self, guild: discord.Guild, parent: discord.Member, child: discord.Member) -> str | None:
        db = self.bot.db
        if child.bot:
            return "Bots can't be adopted. 🤖"
        if parent.id == child.id:
            return "You can't adopt yourself."
        if existing := await db.get_parent(guild.id, child.id):
            return f"{child.display_name} already has a parent (<@{existing}>)."
        spouse = await db.get_marriage(guild.id, parent.id)
        if spouse and spouse["partner_id"] == child.id:
            return "You can't adopt your spouse!"
        if child.id in await self._ancestors(guild.id, parent.id):
            return "You can't adopt your own ancestor!"
        if len(await db.get_children(guild.id, parent.id)) >= config.MAX_CHILDREN:
            return f"You already have {config.MAX_CHILDREN} children, which is the limit."
        return None

    async def _ask(self, ctx: commands.Context, target: discord.Member, prompt: str, view: ProposalView) -> None:
        view.message = await ctx.send(prompt, view=view)

    # ---- marriage ------------------------------------------------------

    @commands.hybrid_command(name="marry", description="Propose to someone.")
    async def marry(self, ctx: commands.Context, member: discord.Member) -> None:
        guild, proposer = ctx.guild, ctx.author
        if problem := await self._marriage_problem(guild, proposer, member):
            await ctx.send(problem, ephemeral=True)
            return

        async def accepted() -> str:
            if problem := await self._marriage_problem(guild, proposer, member):  # things may have changed
                return problem
            if not await self.bot.db.marry(guild.id, proposer.id, member.id):
                return "Sorry, someone got married in the meantime."
            return f"💞 {proposer.mention} and {member.mention} are now **married**! Congratulations!"

        view = ProposalView(
            member,
            accepted,
            accept_label="I do!",
            accept_emoji="💍",
            decline_text=f"💔 {member.mention} turned down {proposer.mention}'s proposal.",
            timeout_text=f"⏳ {member.mention} didn't answer {proposer.mention}'s proposal in time.",
        )
        await self._ask(ctx, member, f"💍 {member.mention}, **{proposer.display_name}** is asking you to marry them!", view)

    @commands.hybrid_command(name="divorce", description="End your marriage.")
    async def divorce(self, ctx: commands.Context) -> None:
        partner_id = await self.bot.db.divorce(ctx.guild.id, ctx.author.id)
        if partner_id is None:
            await ctx.send("You're not married.", ephemeral=True)
            return
        await ctx.send(f"💔 {ctx.author.mention} and <@{partner_id}> are no longer married.")

    # ---- adoption ------------------------------------------------------

    @commands.hybrid_command(name="adopt", description="Ask someone to become your child.")
    async def adopt(self, ctx: commands.Context, member: discord.Member) -> None:
        guild, parent = ctx.guild, ctx.author
        if problem := await self._adoption_problem(guild, parent, member):
            await ctx.send(problem, ephemeral=True)
            return

        async def accepted() -> str:
            if problem := await self._adoption_problem(guild, parent, member):
                return problem
            if not await self.bot.db.adopt(guild.id, parent.id, member.id):
                return f"{member.display_name} already got adopted by someone else."
            return f"👨‍👧 {parent.mention} adopted {member.mention}! Welcome to the family!"

        view = ProposalView(
            member,
            accepted,
            accept_label="Join the family",
            accept_emoji="🏠",
            decline_text=f"{member.mention} declined to be adopted by {parent.mention}.",
            timeout_text=f"⏳ {member.mention} didn't answer {parent.mention} in time.",
        )
        await self._ask(ctx, member, f"🏠 {member.mention}, **{parent.display_name}** wants to adopt you!", view)

    @commands.hybrid_command(name="disown", description="Remove one of your children from your family.")
    async def disown(self, ctx: commands.Context, member: discord.Member) -> None:
        if await self.bot.db.get_parent(ctx.guild.id, member.id) != ctx.author.id:
            await ctx.send(f"{member.display_name} isn't your child.", ephemeral=True)
            return
        await self.bot.db.remove_adoption(ctx.guild.id, member.id)
        await ctx.send(f"💔 {ctx.author.mention} disowned {member.mention}.")

    @commands.hybrid_command(name="runaway", description="Leave your parent's family.")
    async def runaway(self, ctx: commands.Context) -> None:
        parent_id = await self.bot.db.get_parent(ctx.guild.id, ctx.author.id)
        if parent_id is None:
            await ctx.send("You don't have a parent.", ephemeral=True)
            return
        await self.bot.db.remove_adoption(ctx.guild.id, ctx.author.id)
        await ctx.send(f"🏃 {ctx.author.mention} ran away from <@{parent_id}>'s family.")

    # ---- family overview ----------------------------------------------

    @commands.hybrid_command(name="family", aliases=["fam"], description="Show someone's partner, parent and children.")
    async def family(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        member = member or ctx.author
        db, gid = self.bot.db, ctx.guild.id
        marriage = await db.get_marriage(gid, member.id)
        parent = await db.get_parent(gid, member.id)
        children = await db.get_children(gid, member.id)

        embed = discord.Embed(title=f"{member.display_name}'s family", color=discord.Color.pink())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="💍 Partner",
            value=f"<@{marriage['partner_id']}> (since <t:{marriage['married_at']}:D>)" if marriage else "None",
            inline=False,
        )
        embed.add_field(name="🏠 Parent", value=f"<@{parent}>" if parent else "None", inline=False)
        embed.add_field(
            name=f"👶 Children ({len(children)})",
            value=", ".join(f"<@{c}>" for c in children) if children else "None",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Relationships(bot))
