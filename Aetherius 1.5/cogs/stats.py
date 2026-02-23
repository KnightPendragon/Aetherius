"""
Stats cog — /stats command for aggregated quest board statistics.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from collections import Counter

from utils import storage


class StatsCog(commands.Cog):
    """Quest Board statistics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="View Quest Board statistics.")
    @app_commands.describe(
        filter_by="Filter stats by a specific parameter",
        value="Value to filter by (e.g. D&D, ONLINE, ONESHOT…)",
    )
    @app_commands.choices(
        filter_by=[
            app_commands.Choice(name="Status",     value="status"),
            app_commands.Choice(name="Mode",       value="mode"),
            app_commands.Choice(name="Type",       value="quest_type"),
            app_commands.Choice(name="System",     value="system"),
        ]
    )
    async def stats(
        self,
        interaction: discord.Interaction,
        filter_by: Optional[str] = None,
        value: Optional[str] = None,
    ):
        all_quests = storage.get_all_quests()
        quests = list(all_quests.values())

        if filter_by and value:
            quests = [q for q in quests if str(q.get(filter_by, "")).upper() == value.upper()]

        total = len(quests)

        if total == 0:
            await interaction.response.send_message(
                "📭 No quests found matching that filter.", ephemeral=True
            )
            return

        status_count    = Counter(q.get("status", "—")     for q in quests)
        mode_count      = Counter(q.get("mode", "—")       for q in quests)
        type_count      = Counter(q.get("quest_type", "—") for q in quests)
        system_count    = Counter(q.get("system", "—")     for q in quests)

        total_players   = sum(len(q.get("roster", []))   for q in quests)
        total_waitlist  = sum(len(q.get("waitlist", [])) for q in quests)

        def fmt_counter(c: Counter) -> str:
            return "\n".join(f"`{k}`: {v}" for k, v in c.most_common()) or "—"

        embed = discord.Embed(
            title="📊 Quest Board Statistics",
            colour=0x5865F2,
        )

        if filter_by and value:
            embed.description = f"Filtered by **{filter_by.upper()}** = `{value.upper()}`"

        embed.add_field(name="Total Quests",      value=str(total),         inline=True)
        embed.add_field(name="Total Players",     value=str(total_players), inline=True)
        embed.add_field(name="On Waitlists",      value=str(total_waitlist),inline=True)
        embed.add_field(name="By Status",         value=fmt_counter(status_count),  inline=True)
        embed.add_field(name="By Mode",           value=fmt_counter(mode_count),    inline=True)
        embed.add_field(name="By Type",           value=fmt_counter(type_count),    inline=True)
        embed.add_field(name="By System (top 10)",
                        value=fmt_counter(Counter(dict(system_count.most_common(10)))),
                        inline=False)

        await interaction.response.send_message(embed=embed)
