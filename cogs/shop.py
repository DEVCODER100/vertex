"""Server shop: role items bought with Vertex Coins or Credits (incl. Elite → Eternal)."""

import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

import config
from rolesutil import find_role

log = logging.getLogger("vertex.shop")

Price = commands.Range[int, 1, 1_000_000_000]


def fmt_price(price: int, currency: str) -> str:
    if currency == "credits":
        return f"{config.CREDITS_EMOJI} {price:,} {config.CREDITS_NAME}"
    return f"{config.CURRENCY_EMOJI} {price:,} {config.CURRENCY_NAME}"


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---- browsing ------------------------------------------------------

    @commands.hybrid_group(
        name="shop", aliases=["store", "sh"], description="Browse the server shop.", fallback="view",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def shop(self, ctx: commands.Context) -> None:
        items = await self.bot.db.shop_items(ctx.guild.id)
        if not items:
            await ctx.send(
                f"The shop is empty. Admins can run `{config.PREFIX}setuptiers` or `{config.PREFIX}shop add`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="🛒 Server shop", color=discord.Color.gold())
        for currency, heading in (
            ("credits", f"{config.CREDITS_EMOJI} Premium roles ({config.CREDITS_NAME})"),
            ("coins", f"{config.CURRENCY_EMOJI} Items ({config.CURRENCY_NAME})"),
        ):
            lines = []
            for item in (i for i in items if i["currency"] == currency):
                line = f"**{item['name']}** — {fmt_price(item['price'], currency)}\n<@&{item['role_id']}>"
                if item["description"]:
                    line += f" · {item['description']}"
                lines.append(line)
            if lines:
                embed.add_field(name=heading, value="\n\n".join(lines), inline=False)
        embed.set_footer(text=f"Buy with {config.PREFIX}buy <item name>")
        await ctx.send(embed=embed)

    async def _item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        items = await self.bot.db.shop_items(interaction.guild.id)
        current = current.lower()
        return [app_commands.Choice(name=i["name"], value=i["name"]) for i in items if current in i["name"].lower()][:25]

    # ---- buying --------------------------------------------------------

    @commands.hybrid_command(name="buy", description="Buy an item from the shop.")
    @commands.guild_only()
    async def buy(self, ctx: commands.Context, *, item: str) -> None:
        db = self.bot.db
        guild, member = ctx.guild, ctx.author

        entry = await db.get_shop_item(guild.id, item)
        if entry is None:
            await ctx.send(f"There's no item called **{item}**. See `{config.PREFIX}shop`.", ephemeral=True)
            return

        role = guild.get_role(entry["role_id"])
        if role is None:
            await ctx.send("That item's role no longer exists. Tell an admin.", ephemeral=True)
            return
        if role in member.roles:
            await ctx.send(f"You already have {role.mention}.", ephemeral=True)
            return
        if role >= guild.me.top_role or not guild.me.guild_permissions.manage_roles:
            await ctx.send("I can't hand out that role yet. An admin needs to move my role above it.", ephemeral=True)
            return

        price, currency = entry["price"], entry["currency"]
        spend = {"credits": price} if currency == "credits" else {"coins": price}
        if not await db.try_spend(guild.id, member.id, **spend):
            row = await db.get_user(guild.id, member.id)
            have = row["credits"] if currency == "credits" else row["coins"]
            await ctx.send(
                f"You need {fmt_price(price, currency)}, but you only have **{have:,}**.", ephemeral=True
            )
            return

        try:
            await member.add_roles(role, reason=f"Bought '{entry['name']}' in the shop")
        except discord.HTTPException:
            await db.add_balance(guild.id, member.id, **spend)  # refund
            log.exception("Failed to give %s to %s; refunded", role, member)
            await ctx.send("I couldn't give you the role, so you weren't charged.", ephemeral=True)
            return

        await ctx.send(f"🛍️ {member.mention} bought **{entry['name']}** ({role.mention}) for {fmt_price(price, currency)}!")

    @buy.autocomplete("item")
    async def buy_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._item_autocomplete(interaction, current)

    # ---- admin: manage the shop ---------------------------------------

    @shop.command(name="add", description="Admin: add or update a shop item that gives a role.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def shop_add(
        self,
        ctx: commands.Context,
        name: str,
        price: Price,
        currency: Literal["coins", "credits"],
        role: discord.Role,
        *,
        description: str = "",
    ) -> None:
        if role >= ctx.guild.me.top_role:
            await ctx.send("That role is above mine, so I couldn't hand it out. Move my role up first.", ephemeral=True)
            return
        await self.bot.db.upsert_shop_item(ctx.guild.id, name.strip(), description.strip()[:100], price, currency, role.id)
        await ctx.send(f"✅ Saved **{name}** — {fmt_price(price, currency)} → {role.mention}", ephemeral=True)

    @shop.command(name="remove", description="Admin: remove a shop item.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def shop_remove(self, ctx: commands.Context, *, item: str) -> None:
        removed = await self.bot.db.remove_shop_item(ctx.guild.id, item.strip())
        await ctx.send("✅ Removed." if removed else "I couldn't find that item.", ephemeral=True)

    @shop_remove.autocomplete("item")
    async def shop_remove_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._item_autocomplete(interaction, current)

    @commands.hybrid_command(
        name="setuptiers", aliases=["tiers"], description="Admin: create the Elite → Eternal roles and add them to the shop."
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setuptiers(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission first.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        report = []
        for name, price, color in config.TIER_ROLES:
            role = find_role(guild, name)  # also matches roles that already have an emoji after the name
            created = False
            if role is None:
                try:
                    role = await guild.create_role(
                        name=name, colour=discord.Colour(color), reason="Vertex tier roles setup"
                    )
                    created = True
                except discord.HTTPException:
                    log.exception("Couldn't create tier role %s", name)
                    report.append(f"❌ **{name}**: couldn't create the role")
                    continue
            elif role >= guild.me.top_role:
                report.append(f"⚠️ **{name}**: the role exists but is above mine, so I can't give it. Move my role up.")
                continue

            await self.bot.db.upsert_shop_item(guild.id, name, "", price, "credits", role.id)
            report.append(f"✅ **{name}** — {fmt_price(price, 'credits')} ({'created' if created else 'existing role'})")

        await ctx.send("\n".join(report), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shop(bot))
