"""Entry point. Run with:  python bot.py"""

import logging
import sys
from pathlib import Path

import discord
from discord.ext import commands

import config
from database import Database

log = logging.getLogger("vertex")

COGS_DIR = Path(__file__).parent / "cogs"


class VertexBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True  # privileged: "Server Members Intent" in the Developer Portal
        intents.message_content = True  # privileged: "Message Content Intent" (needed for ",command")

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.PREFIX),
            intents=intents,
            help_command=None,  # replaced by our own /help and ,help in cogs/general.py
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )
        self.db = Database(config.DB_PATH)

    async def setup_hook(self) -> None:
        await self.db.connect()

        # Auto-load every cogs/*.py file (skip names starting with "_").
        for path in sorted(COGS_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            await self.load_extension(f"cogs.{path.stem}")
            log.info("Loaded cog: %s", path.stem)

        # Guild sync shows up instantly; global sync can take up to an hour.
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to guild %s", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally", len(synced))

    async def close(self) -> None:
        # Cogs unload inside super().close() and may still need the database (e.g. refunds).
        await super().close()
        await self.db.close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s) in %d server(s)", self.user, self.user.id, len(self.guilds))

    async def on_command(self, ctx: commands.Context) -> None:
        log.info("Command %s%s from %s in #%s", config.PREFIX, ctx.command.qualified_name, ctx.author, ctx.channel)

    async def on_app_command_completion(self, interaction: discord.Interaction, command) -> None:
        log.info("Slash command /%s from %s finished", command.qualified_name, interaction.user)

    async def on_message(self, message: discord.Message) -> None:
        if not message.author.bot and message.content.startswith(config.PREFIX):
            # Helps spot a bot that "can't hear" commands (missing intent or channel permissions).
            log.info("Heard %r from %s in #%s", message.content[:40], message.author, message.channel)
        await self.process_commands(message)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        # A leading "," is common in normal chat, so unknown commands are silently ignored.
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingPermissions):
            message = "You don't have permission to use that command."
        elif isinstance(error, commands.NoPrivateMessage):
            message = "That command only works inside a server."
        elif isinstance(error, commands.CommandOnCooldown):
            message = f"Slow down! Try again in {error.retry_after:.1f}s."
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"You're missing `{error.param.name}`. Try `{config.PREFIX}help`."
        elif isinstance(error, commands.UserInputError):
            message = f"I couldn't understand that. {error}"
        elif isinstance(error, commands.CheckFailure):
            message = "You can't use that command here."
        else:
            log.exception("Unhandled error in command %s", ctx.command, exc_info=error)
            message = "Something went wrong on my end. Try again in a moment."

        try:
            await ctx.send(message, ephemeral=True)
        except discord.HTTPException:
            pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if not config.TOKEN:
        sys.exit("DISCORD_TOKEN is missing. Copy .env.example to .env and fill it in.")

    VertexBot().run(config.TOKEN, log_handler=None)  # we configured logging ourselves


if __name__ == "__main__":
    main()
