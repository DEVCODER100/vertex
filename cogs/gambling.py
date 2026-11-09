"""Gambling with Vertex Coins: coinflip, slots, dice and blackjack."""

import asyncio
import logging
from typing import Literal

import discord
from discord.ext import commands

import config
import games

log = logging.getLogger("vertex.gambling")

COIN = config.CURRENCY_EMOJI
GREEN, RED, GOLD, BLURPLE = (
    discord.Color.green(),
    discord.Color.red(),
    discord.Color.gold(),
    discord.Color.blurple(),
)

cooldown = commands.cooldown(1, config.GAMBLING_COOLDOWN_SECONDS, commands.BucketType.user)


def _result_embed(title: str, body: str, bet: int, returned: int, balance: int) -> discord.Embed:
    net = returned - bet
    if net > 0:
        color, summary = GREEN, f"You won **{net:,}** {COIN}"
    elif net == 0:
        color, summary = GOLD, "You got your bet back"
    else:
        color, summary = RED, f"You lost **{-net:,}** {COIN}"
    embed = discord.Embed(title=title, description=f"{body}\n\n{summary}", color=color)
    embed.set_footer(text=f"Balance: {balance:,} {config.CURRENCY_NAME}")
    return embed


class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Gambling", ctx: commands.Context, game: games.BlackjackGame) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.game = game
        self.message: discord.Message | None = None
        self.finished = False
        self._lock = asyncio.Lock()

    # ---- display -------------------------------------------------------

    def table(self, reveal: bool) -> str:
        g = self.game
        if reveal:
            dealer = f"{games.hand_str(g.dealer)}  (**{g.dealer_total}**)"
        else:
            dealer = f"{games.card_str(g.dealer[0])} `??`"
        return f"**Dealer**\n{dealer}\n\n**You**\n{games.hand_str(g.player)}  (**{g.player_total}**)"

    def playing_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🃏 Blackjack", description=self.table(reveal=False), color=BLURPLE)
        embed.set_footer(text=f"Bet: {self.game.bet:,} {config.CURRENCY_NAME} · Dealer stands on 17")
        return embed

    async def final_embed(self, result: str, returned: int) -> discord.Embed:
        titles = {
            "blackjack": "🃏 Blackjack! Pays 3:2",
            "win": "🃏 You win!",
            "push": "🃏 Push",
            "lose": "🃏 Dealer wins",
            "bust": "🃏 Bust!",
        }
        row = await self.cog.bot.db.get_user(self.ctx.guild.id, self.ctx.author.id)
        return _result_embed(titles[result], self.table(reveal=True), self.game.bet, returned, row["coins"])

    # ---- flow -----------------------------------------------------------

    async def settle(self, result: str, returned: int) -> discord.Embed:
        """Pay out, free the player's table slot, and build the final embed."""
        self.finished = True
        self.stop()
        if returned:
            await self.cog.bot.db.add_balance(self.ctx.guild.id, self.ctx.author.id, coins=returned)
        self.cog.tables.pop((self.ctx.guild.id, self.ctx.author.id), None)
        return await self.final_embed(result, returned)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This isn't your game.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Hit", emoji="➕", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.finished:
                return
            self.game.hit()
            self.double.disabled = True
            if self.game.player_total < 21:
                await interaction.response.edit_message(embed=self.playing_embed(), view=self)
                return
            result, returned = self.game.outcome()  # bust, or 21 -> stand automatically
            embed = await self.settle(result, returned)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Stand", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.finished:
                return
            result, returned = self.game.outcome()
            embed = await self.settle(result, returned)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Double", emoji="✖️", style=discord.ButtonStyle.success)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.finished:
                return
            if len(self.game.player) != 2:
                await interaction.response.send_message("You can only double on your first move.", ephemeral=True)
                return
            if not await self.cog.bot.db.try_spend(self.ctx.guild.id, self.ctx.author.id, coins=self.game.bet):
                await interaction.response.send_message("You don't have enough to double.", ephemeral=True)
                return
            self.game.bet *= 2
            self.game.hit()
            result, returned = self.game.outcome()
            embed = await self.settle(result, returned)
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self) -> None:
        """Walked away? Stand for them so their coins aren't stuck."""
        async with self._lock:
            if self.finished:
                return
            result, returned = self.game.outcome()
            embed = await self.settle(result, returned)
        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass


class Gambling(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tables: dict[tuple[int, int], BlackjackView] = {}

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def cog_unload(self) -> None:
        """Bot is shutting down: give back the stake of every unfinished blackjack hand."""
        for (guild_id, user_id), view in list(self.tables.items()):
            try:
                await self.bot.db.add_balance(guild_id, user_id, coins=view.game.bet)
            except Exception:
                log.exception("Couldn't refund blackjack stake for %s", user_id)
        self.tables.clear()

    # ---- shared ---------------------------------------------------------

    async def _take_bet(self, ctx: commands.Context, text: str) -> int | None:
        """Parse the bet, validate it, and take it from the wallet. None (with a message sent) on failure."""
        row = await self.bot.db.get_user(ctx.guild.id, ctx.author.id)
        try:
            bet = games.parse_amount(text, row["coins"])
        except ValueError as error:
            await ctx.send(str(error), ephemeral=True)
            return None
        if bet < config.MIN_BET:
            await ctx.send(f"The minimum bet is **{config.MIN_BET:,}** {COIN}.", ephemeral=True)
            return None
        if bet > row["coins"]:
            await ctx.send(f"You only have **{row['coins']:,}** {COIN}.", ephemeral=True)
            return None
        if not await self.bot.db.try_spend(ctx.guild.id, ctx.author.id, coins=bet):
            await ctx.send("Your balance changed. Try again.", ephemeral=True)
            return None
        return bet

    async def _settle_simple(self, ctx: commands.Context, bet: int, returned: int) -> int:
        """Pay out a one-shot game and return the new balance."""
        if returned:
            row = await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, coins=returned)
        else:
            row = await self.bot.db.get_user(ctx.guild.id, ctx.author.id)
        return row["coins"]

    # ---- coinflip -------------------------------------------------------

    @commands.hybrid_command(name="coinflip", aliases=["cf", "flip"], description="Bet on heads or tails.")
    @cooldown
    async def coinflip(
        self, ctx: commands.Context, amount: str, choice: Literal["heads", "tails"] = "heads"
    ) -> None:
        bet = await self._take_bet(ctx, amount)
        if bet is None:
            return
        landed = games.rng.choice(["heads", "tails"])
        returned = games.payout(bet, games.COINFLIP_PAYOUT) if landed == choice else 0
        balance = await self._settle_simple(ctx, bet, returned)
        body = f"You picked **{choice}**. The coin landed on **{landed}**! 🪙"
        await ctx.send(embed=_result_embed("🪙 Coinflip", body, bet, returned, balance))

    # ---- slots ----------------------------------------------------------

    @commands.hybrid_command(name="slots", aliases=["slot", "sl"], description="Spin the slot machine.")
    @cooldown
    async def slots(self, ctx: commands.Context, amount: str) -> None:
        bet = await self._take_bet(ctx, amount)
        if bet is None:
            return
        reels = games.spin_reels()
        multiplier = games.slot_multiplier(reels)
        returned = bet * multiplier
        balance = await self._settle_simple(ctx, bet, returned)  # paid before the animation, so it's safe

        spinning = discord.Embed(title="🎰 Slots", description="| 🎰 | 🎰 | 🎰 |\n\nSpinning...", color=BLURPLE)
        message = await ctx.send(embed=spinning)
        await asyncio.sleep(1.2)

        line = "| " + " | ".join(reels) + " |"
        body = f"{line}\n\n" + (f"**{multiplier}x** payout!" if multiplier else "No match.")
        final = _result_embed("🎰 Slots", body, bet, returned, balance)
        try:
            await message.edit(embed=final)
        except discord.HTTPException:
            await ctx.send(embed=final)

    # ---- dice -----------------------------------------------------------

    @commands.hybrid_command(
        name="dice", aliases=["roll"], description="Bet on a die roll: high, low, or an exact number."
    )
    @cooldown
    async def dice(
        self, ctx: commands.Context, amount: str, choice: Literal["high", "low", "1", "2", "3", "4", "5", "6"]
    ) -> None:
        bet = await self._take_bet(ctx, amount)
        if bet is None:
            return
        roll = games.rng.randint(1, 6)
        if choice == "high":
            won, multiplier = roll >= 4, games.DICE_HILO_PAYOUT
        elif choice == "low":
            won, multiplier = roll <= 3, games.DICE_HILO_PAYOUT
        else:
            won, multiplier = roll == int(choice), games.DICE_EXACT_PAYOUT
        returned = games.payout(bet, multiplier) if won else 0
        balance = await self._settle_simple(ctx, bet, returned)
        body = f"You bet on **{choice}**. The die shows 🎲 **{roll}**!"
        await ctx.send(embed=_result_embed("🎲 Dice", body, bet, returned, balance))

    # ---- blackjack ------------------------------------------------------

    @commands.hybrid_command(name="blackjack", aliases=["bj"], description="Play blackjack against the dealer.")
    @cooldown
    async def blackjack(self, ctx: commands.Context, amount: str) -> None:
        key = (ctx.guild.id, ctx.author.id)
        if key in self.tables:
            await ctx.send("You already have a blackjack hand in play. Finish it first!", ephemeral=True)
            return
        bet = await self._take_bet(ctx, amount)
        if bet is None:
            return

        game = games.BlackjackGame(bet)
        view = BlackjackView(self, ctx, game)

        natural = game.natural_outcome()
        if natural is not None:
            result, returned = natural
            embed = await view.settle(result, returned)
            await ctx.send(embed=embed)
            return

        self.tables[key] = view
        view.message = await ctx.send(embed=view.playing_embed(), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gambling(bot))
