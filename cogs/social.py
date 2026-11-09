"""Anime-style interaction commands: ,hug @user  ,slap @user  ,wave  ...

GIFs come from a free API (otakugifs.xyz). Put your own links in data/gifs.json to override
any action, e.g. {"kill": ["https://example.com/a.gif"]}.
"""

import json
import logging
import random
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands

import config

log = logging.getLogger("vertex.social")

# action -> (API reaction, emoji, message templates). {a} = you, {b} = target.
TARGETED = {
    "hug": ("hug", "🤗", ["{a} gives {b} a big hug!"]),
    "kiss": ("kiss", "😘", ["{a} kisses {b}!"]),
    "pat": ("pat", "🥰", ["{a} pats {b} on the head."]),
    "slap": ("slap", "✋", ["{a} slaps {b}!"]),
    "kill": (
        "punch",
        "💀",
        [
            "{a} sent {b} flying into the sun ☀️ (they respawn in 5 minutes)",
            "{a} dropped an anvil on {b} 🔨... cartoon-style, so {b} walked it off.",
            "{a} defeated {b} in an epic duel ⚔️ and {b} came back with a rematch.",
        ],
    ),
    "cuddle": ("cuddle", "🫂", ["{a} cuddles {b}."]),
    "poke": ("poke", "👉", ["{a} pokes {b}."]),
    "bite": ("bite", "😬", ["{a} bites {b}! Nom."]),
    "punch": ("punch", "👊", ["{a} punches {b}!"]),
    "tickle": ("tickle", "🤭", ["{a} tickles {b}!"]),
    "handhold": ("handhold", "🤝", ["{a} holds {b}'s hand."]),
    "highfive": ("brofist", "🙌", ["{a} high-fives {b}!"]),
    "nuzzle": ("nuzzle", "💞", ["{a} nuzzles {b}."]),
}
SELF_OK = {"hug", "pat"}  # actions you may do to yourself

# action -> (API reaction, emoji, text alone, text aimed at someone)
SOLO = {
    "wave": ("wave", "👋", "{a} waves.", "{a} waves at {b}!"),
    "wink": ("wink", "😉", "{a} winks.", "{a} winks at {b}."),
    "cry": ("cry", "😭", "{a} is crying...", "{a} cries on {b}'s shoulder."),
    "blush": ("blush", "😊", "{a} blushes.", "{a} blushes because of {b}."),
    "dance": ("dance", "💃", "{a} dances!", "{a} dances with {b}!"),
    "smile": ("smile", "😄", "{a} smiles.", "{a} smiles at {b}."),
    "laugh": ("laugh", "😂", "{a} bursts out laughing!", "{a} laughs with {b}!"),
    "pout": ("pout", "😤", "{a} pouts.", "{a} pouts at {b}."),
    "nom": ("nom", "😋", "{a} munches away.", "{a} nibbles on {b}."),
    "sleep": ("sleep", "😴", "{a} falls asleep.", "{a} falls asleep next to {b}."),
    "shrug": ("shrug", "🤷", "{a} shrugs.", "{a} shrugs at {b}."),
    "facepalm": ("facepalm", "🤦", "{a} facepalms.", "{a} facepalms because of {b}."),
}


def _ordinal_times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


class Social(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self.custom_gifs: dict[str, list[str]] = {}

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6),
            headers={"User-Agent": "VertexBot/1.0 (Discord bot for a private server)"},
        )
        path = Path(config.CUSTOM_GIFS_PATH)
        if path.exists():
            try:
                self.custom_gifs = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("Couldn't read %s; ignoring it.", path)

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # ---- helpers -------------------------------------------------------

    async def _gif_for(self, action: str, reaction: str) -> str | None:
        custom = self.custom_gifs.get(action)
        if custom:
            return random.choice(custom)
        try:
            async with self.session.get(config.GIF_API_URL, params={"reaction": reaction}) as resp:
                if resp.status != 200:
                    return None
                return (await resp.json()).get("url")
        except (aiohttp.ClientError, TimeoutError, ValueError):
            log.warning("GIF API failed for %s; sending text only.", action)
            return None

    async def _targeted(self, ctx: commands.Context, action: str, member: discord.Member) -> None:
        reaction, emoji, templates = TARGETED[action]
        if member.bot:
            await ctx.send("Bots don't have feelings... pick a human! 🤖", ephemeral=True)
            return
        if member.id == ctx.author.id and action not in SELF_OK:
            await ctx.send("Be kind to yourself! 💜 Pick someone else.", ephemeral=True)
            return

        text = random.choice(templates).format(a=f"**{ctx.author.display_name}**", b=f"**{member.display_name}**")
        embed = discord.Embed(description=f"{emoji} {text}", color=discord.Color.pink())
        if gif := await self._gif_for(action, reaction):
            embed.set_image(url=gif)

        if member.id != ctx.author.id:
            n = await self.bot.db.bump_interaction(ctx.guild.id, ctx.author.id, member.id, action)
            embed.set_footer(text=f"{ctx.author.display_name} has used {action} on {member.display_name} {_ordinal_times(n)}")
        await ctx.send(embed=embed)

    async def _solo(self, ctx: commands.Context, action: str, member: discord.Member | None) -> None:
        reaction, emoji, alone, aimed = SOLO[action]
        a = f"**{ctx.author.display_name}**"
        if member is not None and not member.bot and member.id != ctx.author.id:
            text = aimed.format(a=a, b=f"**{member.display_name}**")
        else:
            text = alone.format(a=a)

        embed = discord.Embed(description=f"{emoji} {text}", color=discord.Color.pink())
        if gif := await self._gif_for(action, reaction):
            embed.set_image(url=gif)
        await ctx.send(embed=embed)

    # ---- actions that need a target -----------------------------------

    @commands.hybrid_command(name="hug", description="Give someone a warm hug.")
    async def hug(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "hug", member)

    @commands.hybrid_command(name="kiss", description="Give someone a kiss.")
    async def kiss(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "kiss", member)

    @commands.hybrid_command(name="pat", description="Pat someone on the head.")
    async def pat(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "pat", member)

    @commands.hybrid_command(name="slap", description="Slap someone.")
    async def slap(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "slap", member)

    @commands.hybrid_command(name="kill", description="Cartoon-style defeat of someone (they respawn).")
    async def kill(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "kill", member)

    @commands.hybrid_command(name="cuddle", description="Cuddle someone.")
    async def cuddle(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "cuddle", member)

    @commands.hybrid_command(name="poke", description="Poke someone.")
    async def poke(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "poke", member)

    @commands.hybrid_command(name="bite", description="Bite someone.")
    async def bite(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "bite", member)

    @commands.hybrid_command(name="punch", description="Punch someone.")
    async def punch(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "punch", member)

    @commands.hybrid_command(name="tickle", description="Tickle someone.")
    async def tickle(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "tickle", member)

    @commands.hybrid_command(name="handhold", aliases=["hh"], description="Hold someone's hand.")
    async def handhold(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "handhold", member)

    @commands.hybrid_command(name="highfive", aliases=["hf", "five"], description="High-five someone.")
    async def highfive(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "highfive", member)

    @commands.hybrid_command(name="nuzzle", description="Nuzzle someone.")
    async def nuzzle(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._targeted(ctx, "nuzzle", member)

    # ---- actions with an optional target ------------------------------

    @commands.hybrid_command(name="wave", description="Wave (optionally at someone).")
    async def wave(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "wave", member)

    @commands.hybrid_command(name="wink", description="Wink (optionally at someone).")
    async def wink(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "wink", member)

    @commands.hybrid_command(name="cry", description="Cry (optionally on someone's shoulder).")
    async def cry(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "cry", member)

    @commands.hybrid_command(name="blush", description="Blush.")
    async def blush(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "blush", member)

    @commands.hybrid_command(name="dance", description="Dance (optionally with someone).")
    async def dance(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "dance", member)

    @commands.hybrid_command(name="smile", description="Smile.")
    async def smile(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "smile", member)

    @commands.hybrid_command(name="laugh", description="Laugh.")
    async def laugh(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "laugh", member)

    @commands.hybrid_command(name="pout", description="Pout.")
    async def pout(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "pout", member)

    @commands.hybrid_command(name="nom", description="Nom nom nom.")
    async def nom(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "nom", member)

    @commands.hybrid_command(name="sleep", description="Fall asleep.")
    async def sleep(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "sleep", member)

    @commands.hybrid_command(name="shrug", description="Shrug.")
    async def shrug(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "shrug", member)

    @commands.hybrid_command(name="facepalm", description="Facepalm.")
    async def facepalm(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._solo(ctx, "facepalm", member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Social(bot))
