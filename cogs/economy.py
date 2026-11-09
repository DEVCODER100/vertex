"""Vertex Coins (server money) and Credits (premium currency)."""

import time

import discord
from discord import app_commands
from discord.ext import commands

import config

COINS = f"{config.CURRENCY_EMOJI} {config.CURRENCY_NAME}"
CREDITS = f"{config.CREDITS_EMOJI} {config.CREDITS_NAME}"

Amount = commands.Range[int, 1, 1_000_000_000]


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="balance", aliases=["bal", "b", "wallet", "money"], description="Check your money and Credits.")
    @commands.guild_only()
    async def balance(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        member = member or ctx.author
        row = await self.bot.db.get_user(ctx.guild.id, member.id)
        embed = discord.Embed(title=f"{member.display_name}'s wallet", color=discord.Color.gold())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name=config.CURRENCY_NAME, value=f"{config.CURRENCY_EMOJI} {row['coins']:,}")
        embed.add_field(name=config.CREDITS_NAME, value=f"{config.CREDITS_EMOJI} {row['credits']:,}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="daily", aliases=["d"], description=f"Claim your daily {config.CURRENCY_NAME}.")
    @commands.guild_only()
    async def daily(self, ctx: commands.Context) -> None:
        ok, value = await self.bot.db.claim_daily(
            ctx.guild.id, ctx.author.id, config.DAILY_AMOUNT, config.DAILY_COOLDOWN_SECONDS
        )
        if ok:
            await ctx.send(
                f"✅ You claimed **{config.DAILY_AMOUNT:,}** {COINS}!\nYour balance: **{value:,}**"
            )
        else:
            ready_at = int(time.time()) + value
            await ctx.send(f"⏳ Your daily isn't ready. Come back <t:{ready_at}:R>.")

    @commands.hybrid_command(name="give", aliases=["pay", "send"], description=f"Send {config.CURRENCY_NAME} to a member.")
    @commands.guild_only()
    async def give(self, ctx: commands.Context, member: discord.Member, amount: Amount) -> None:
        if member.bot or member.id == ctx.author.id:
            await ctx.send("You can only give to other real members.", ephemeral=True)
            return
        if not await self.bot.db.transfer_coins(ctx.guild.id, ctx.author.id, member.id, amount):
            await ctx.send(f"You don't have {amount:,} {config.CURRENCY_NAME}.", ephemeral=True)
            return
        await ctx.send(f"💸 {ctx.author.mention} sent **{amount:,}** {COINS} to {member.mention}.")

    # ---- admin tools ---------------------------------------------------

    @commands.hybrid_command(name="addcoins", aliases=["ac"], description=f"Admin: give {config.CURRENCY_NAME} to a member.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def addcoins(self, ctx: commands.Context, member: discord.Member, amount: Amount) -> None:
        row = await self.bot.db.add_balance(ctx.guild.id, member.id, coins=amount)
        await ctx.send(f"✅ Gave {member.mention} **{amount:,}** {COINS}. They now have **{row['coins']:,}**.")

    @commands.hybrid_command(name="addcredits", aliases=["acr"], description=f"Admin: give {config.CREDITS_NAME} to a member.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def addcredits(self, ctx: commands.Context, member: discord.Member, amount: Amount) -> None:
        row = await self.bot.db.add_balance(ctx.guild.id, member.id, credits=amount)
        await ctx.send(f"✅ Gave {member.mention} **{amount:,}** {CREDITS}. They now have **{row['credits']:,}**.")

    @commands.hybrid_command(name="removecoins", aliases=["rmc"], description=f"Admin: take {config.CURRENCY_NAME} from a member.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def removecoins(self, ctx: commands.Context, member: discord.Member, amount: Amount) -> None:
        row = await self.bot.db.add_balance(ctx.guild.id, member.id, coins=-amount)
        await ctx.send(f"✅ Took {COINS} from {member.mention}. They now have **{row['coins']:,}**.")

    @commands.hybrid_command(name="removecredits", aliases=["rmcr"], description=f"Admin: take {config.CREDITS_NAME} from a member.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def removecredits(self, ctx: commands.Context, member: discord.Member, amount: Amount) -> None:
        row = await self.bot.db.add_balance(ctx.guild.id, member.id, credits=-amount)
        await ctx.send(f"✅ Took {CREDITS} from {member.mention}. They now have **{row['credits']:,}**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
