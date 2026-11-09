"""Top-10 leaderboards for XP, coins and credits."""

from typing import Literal

import discord
from discord.ext import commands

import config

BOARDS = {
    "xp": (
        "🏆 XP leaderboard",
        lambda v, level, prestige: (f"⭐{prestige} · " if prestige else "") + f"Level {level} · {v:,} XP",
    ),
    "coins": (f"{config.CURRENCY_EMOJI} {config.CURRENCY_NAME} leaderboard", lambda v, level, prestige: f"{v:,}"),
    "credits": (f"{config.CREDITS_EMOJI} {config.CREDITS_NAME} leaderboard", lambda v, level, prestige: f"{v:,}"),
}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="leaderboard", aliases=["lb", "top"], description="Show the top 10 members (xp, coins or credits)."
    )
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context, board: Literal["xp", "coins", "credits"] = "xp") -> None:
        title, fmt = BOARDS[board]
        rows = await self.bot.db.top(ctx.guild.id, board, limit=10)
        if not rows:
            await ctx.send("Nobody's on this leaderboard yet. Start chatting! 💬")
            return

        lines = [
            f"{MEDALS.get(i, f'`#{i}`')} <@{row['user_id']}> — **{fmt(row['value'], row['level'], row['prestige'])}**"
            for i, row in enumerate(rows, start=1)
        ]
        embed = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())
        embed.set_footer(text=f"Try {config.PREFIX}leaderboard xp | coins | credits")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))
