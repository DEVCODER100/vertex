"""Random quiz drops: flags, math and trivia with clickable answer buttons."""

import asyncio
import collections
import logging
import time
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

import config
import quiz
from games import rng

log = logging.getLogger("vertex.quiz")

KIND_STYLE = {
    "flag": ("🏳️", discord.Color.blue()),
    "math": ("➗", discord.Color.orange()),
    "trivia": ("🧠", discord.Color.purple()),
}


def _reward_text(reward: quiz.Reward) -> str:
    if reward.credits:
        prize = f"{config.CREDITS_EMOJI} **{reward.credits:,}** {config.CREDITS_NAME}"
    else:
        prize = f"{config.CURRENCY_EMOJI} **{reward.coins:,}** {config.CURRENCY_NAME}"
    return f"{prize} + ✨ **{reward.xp}** XP"


class QuizView(discord.ui.View):
    def __init__(self, cog: "Quiz", channel: discord.abc.Messageable, question: quiz.Question) -> None:
        super().__init__(timeout=None)  # expiry is handled by our own fixed timer below
        self.cog = cog
        self.channel = channel
        self.question = question
        self.message: discord.Message | None = None
        self.done = False
        self.wrong: set[int] = set()
        self._lock = asyncio.Lock()
        self._expiry: asyncio.Task | None = None

        for index, label in enumerate(question.labels):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            button.callback = self._make_callback(index)
            self.add_item(button)

    # ---- display -------------------------------------------------------

    def question_embed(self) -> discord.Embed:
        q = self.question
        emoji, color = KIND_STYLE[q.kind]
        description = q.prompt
        if q.letters:
            description += "\n\n" + "\n".join(f"**{quiz.LETTERS[i]})** {opt}" for i, opt in enumerate(q.options))
        embed = discord.Embed(title=f"{emoji} {q.title}", description=description, color=color)
        if q.image_url:
            embed.set_image(url=q.image_url)
        embed.set_footer(
            text=f"First correct answer wins! {config.QUIZ_ANSWER_SECONDS}s · one guess each · "
            "prize: random coins or Credits + XP"
        )
        return embed

    def _lock_buttons(self) -> None:
        for index, item in enumerate(self.children):
            item.disabled = True
            if index == self.question.answer_index:
                item.style = discord.ButtonStyle.success

    # ---- flow ----------------------------------------------------------

    def start(self) -> None:
        self._expiry = asyncio.create_task(self._expire())

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self._answer(interaction, index)

        return callback

    async def _answer(self, interaction: discord.Interaction, index: int) -> None:
        user = interaction.user
        async with self._lock:
            if self.done:
                await interaction.response.send_message("Too late, someone already got it!", ephemeral=True)
                return
            if user.id in self.wrong:
                await interaction.response.send_message("You already used your guess on this one.", ephemeral=True)
                return
            if index != self.question.answer_index:
                self.wrong.add(user.id)
                await interaction.response.send_message("❌ Not quite. You're out for this question.", ephemeral=True)
                return
            self.done = True
            if self._expiry:
                self._expiry.cancel()
            self.cog.active.pop(self.channel.id, None)

        reward = await self.cog.give_reward(user, self.channel)
        self._lock_buttons()
        embed = discord.Embed(
            title=f"✅ {user.display_name} got it!",
            description=f"{self.question.prompt}\n\nAnswer: **{self.question.answer_text}**\n\n🎁 {user.mention} won {_reward_text(reward)}",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def _expire(self) -> None:
        await asyncio.sleep(config.QUIZ_ANSWER_SECONDS)
        async with self._lock:
            if self.done:
                return
            self.done = True
        self.cog.active.pop(self.channel.id, None)
        self._lock_buttons()
        embed = discord.Embed(
            title="⏰ Time's up!",
            description=f"{self.question.prompt}\n\nThe answer was **{self.question.answer_text}**.",
            color=discord.Color.dark_grey(),
        )
        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
        self.stop()


class Quiz(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active: dict[int, QuizView] = {}
        self.recent: collections.deque[str] = collections.deque(maxlen=25)
        self._chat_times: collections.deque[float] = collections.deque(maxlen=100)
        self._task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        if config.QUIZ_CHANNEL_ID is None:
            log.info("QUIZ_CHANNEL_ID is not set, so automatic quiz drops are off.")
            return
        self._task = asyncio.create_task(self._scheduler())

    async def cog_unload(self) -> None:
        if self._task:
            self._task.cancel()
        for view in list(self.active.values()):
            if view._expiry:
                view._expiry.cancel()

    # ---- scheduling ----------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.author.bot and message.channel.id == config.QUIZ_CHANNEL_ID:
            self._chat_times.append(time.monotonic())

    def chat_is_active(self) -> bool:
        cutoff = time.monotonic() - config.QUIZ_ACTIVE_WINDOW_MINUTES * 60
        return sum(1 for t in self._chat_times if t >= cutoff) >= config.QUIZ_ACTIVE_MIN_MESSAGES

    async def _scheduler(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(rng.uniform(config.QUIZ_MIN_MINUTES, config.QUIZ_MAX_MINUTES) * 60)
            while not self.chat_is_active():  # nobody's talking: wait until they are
                await asyncio.sleep(60)
            channel = self.bot.get_channel(config.QUIZ_CHANNEL_ID)
            if channel is None:
                log.warning("Quiz channel %s not found. Is the ID right and can I see it?", config.QUIZ_CHANNEL_ID)
                continue
            try:
                await self.drop(channel)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Quiz drop failed")

    # ---- dropping and rewarding -----------------------------------------

    async def drop(self, channel: discord.abc.Messageable, kind: str | None = None) -> bool:
        """Post a question. False if one is already running in that channel."""
        if channel.id in self.active:
            return False
        question = quiz.make_question(kind, self.recent)
        self.recent.append(question.key)

        view = QuizView(self, channel, question)
        self.active[channel.id] = view
        try:
            view.message = await channel.send(embed=view.question_embed(), view=view)
        except discord.HTTPException:
            self.active.pop(channel.id, None)
            raise
        view.start()
        return True

    async def give_reward(self, member: discord.Member, channel: discord.abc.Messageable) -> quiz.Reward:
        reward = quiz.roll_reward()
        await self.bot.db.add_balance(member.guild.id, member.id, coins=reward.coins, credits=reward.credits)
        leveling = self.bot.get_cog("Leveling")
        if leveling is not None:
            await leveling.award_xp(channel, member, reward.xp)
        else:
            await self.bot.db.add_xp(member.guild.id, member.id, reward.xp)
        return reward

    # ---- admin ---------------------------------------------------------

    @commands.hybrid_command(name="quizdrop", aliases=["quiz"], description="Admin: drop a quiz question in this channel right now.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def quizdrop(
        self, ctx: commands.Context, kind: Literal["random", "flag", "math", "trivia"] = "random"
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await self.drop(ctx.channel, kind):
            await ctx.send("There's already a question running in this channel.", ephemeral=True)
            return
        await ctx.send("Dropped! (Real prizes are paid out to whoever wins.)", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Quiz(bot))
