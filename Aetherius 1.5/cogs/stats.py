"""
Stats cog — /stats command group for Quest Board statistics.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from collections import Counter

from utils import storage


QUESTS_PER_PAGE = 10


def _get_guild_quests(guild_id: int) -> list:
    """Return all quests belonging to a guild, sorted newest first."""
    quests = [
        {**q, "quest_id": qid}
        for qid, q in storage.get_all_quests().items()
        if q.get("guild_id") == guild_id
    ]
    return sorted(quests, key=lambda q: q["quest_id"], reverse=True)


def _fmt_counter(c: Counter) -> str:
    return "\n".join(f"`{k}`: {v}" for k, v in c.most_common()) or "—"


# ── Quest List Paginator (used by /quest list) ─────────────────────────────────

def _build_quest_list_embed(quests: list, page: int, total_pages: int) -> discord.Embed:
    """Build a single page of the quest list."""
    start  = page * QUESTS_PER_PAGE
    end    = start + QUESTS_PER_PAGE
    slice_ = quests[start:end]

    lines = []
    for q in slice_:
        quest_id = q.get("quest_id", "—")
        title    = q.get("title", "Untitled Quest")
        status   = q.get("status", "—")
        lines.append(f"`{quest_id}` — **{title}** `[{status}]`")

    embed = discord.Embed(
        title="📜 Registered Quests",
        description="\n".join(lines) or "No quests on this page.",
        colour=0x5865F2,
    )
    embed.set_footer(text=f"Page {page + 1} of {total_pages}  •  {len(quests)} quest(s) total")
    return embed


class QuestListView(discord.ui.View):
    """Paginated view for scrolling through the quest list."""

    def __init__(self, quests: list, interaction: discord.Interaction):
        super().__init__(timeout=120)
        self.quests      = quests
        self.page        = 0
        self.total_pages = max(1, -(-len(quests) // QUESTS_PER_PAGE))
        self.interaction = interaction
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=_build_quest_list_embed(self.quests, self.page, self.total_pages),
            view=self,
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=_build_quest_list_embed(self.quests, self.page, self.total_pages),
            view=self,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.interaction.edit_original_response(view=self)
        except Exception:
            pass


# ── Cog ───────────────────────────────────────────────────────────────────────

class StatsCog(commands.Cog):
    """Quest Board statistics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    stats_group = app_commands.Group(name="stats", description="Quest Board statistics commands")

    # ── /stats overview ───────────────────────────────────────────────────────
    @stats_group.command(name="overview", description="Show a full overview of all Quest Board stats.")
    async def stats_overview(self, interaction: discord.Interaction):
        quests = _get_guild_quests(interaction.guild_id)

        if not quests:
            await interaction.response.send_message(
                "📭 No quests found on this server.", ephemeral=True
            )
            return

        status_count  = Counter(q.get("status", "—")    for q in quests)
        mode_count    = Counter(q.get("mode", "—")       for q in quests)
        type_count    = Counter(q.get("quest_type", "—") for q in quests)
        system_count  = Counter(q.get("system", "—")     for q in quests)

        total_quests  = len(quests)
        total_players = sum(len(q.get("roster", [])) for q in quests)

        # Most active DMs (top 5)
        dm_count = Counter(q.get("dm_id") for q in quests)
        top_dms  = "\n".join(
            f"{i+1}. <@{dm_id}> — {count} quest(s)"
            for i, (dm_id, count) in enumerate(dm_count.most_common(5))
            if dm_id
        ) or "—"

        # Average roster size (excluding empty quests)
        rosters    = [len(q.get("roster", [])) for q in quests if q.get("roster")]
        avg_roster = f"{sum(rosters) / len(rosters):.1f}" if rosters else "—"

        embed = discord.Embed(
            title="📊 Quest Board — Full Overview",
            colour=0x5865F2,
        )

        embed.add_field(name="Total Quests",     value=str(total_quests),  inline=True)
        embed.add_field(name="Total Players",    value=str(total_players), inline=True)
        embed.add_field(name="Avg. Roster Size", value=avg_roster,         inline=True)
        embed.add_field(name="By Status",        value=_fmt_counter(status_count), inline=True)
        embed.add_field(name="By Mode",          value=_fmt_counter(mode_count),   inline=True)
        embed.add_field(name="By Type",          value=_fmt_counter(type_count),   inline=True)
        embed.add_field(
            name="By System (top 10)",
            value=_fmt_counter(Counter(dict(system_count.most_common(10)))),
            inline=True,
        )
        embed.add_field(name="Most Active DMs",  value=top_dms, inline=True)
        embed.set_footer(text="Use /quest list to browse all registered quests.")

        await interaction.response.send_message(embed=embed)

    # ── /stats view ───────────────────────────────────────────────────────────
    @stats_group.command(name="view", description="View Quest Board statistics filtered by a parameter.")
    @app_commands.describe(
        filter_by="Filter stats by a specific parameter",
        value="Value to filter by (e.g. D&D, ONLINE, ONESHOT…)",
    )
    @app_commands.choices(
        filter_by=[
            app_commands.Choice(name="Status", value="status"),
            app_commands.Choice(name="Mode",   value="mode"),
            app_commands.Choice(name="Type",   value="quest_type"),
            app_commands.Choice(name="System", value="system"),
        ]
    )
    async def stats_view(
        self,
        interaction: discord.Interaction,
        filter_by: Optional[str] = None,
        value: Optional[str] = None,
    ):
        quests = _get_guild_quests(interaction.guild_id)

        if filter_by and value:
            quests = [q for q in quests if str(q.get(filter_by, "")).upper() == value.upper()]

        total = len(quests)
        if total == 0:
            await interaction.response.send_message(
                "📭 No quests found matching that filter.", ephemeral=True
            )
            return

        status_count  = Counter(q.get("status", "—")    for q in quests)
        mode_count    = Counter(q.get("mode", "—")       for q in quests)
        type_count    = Counter(q.get("quest_type", "—") for q in quests)
        system_count  = Counter(q.get("system", "—")     for q in quests)
        total_players = sum(len(q.get("roster", []))     for q in quests)

        embed = discord.Embed(title="📊 Quest Board Statistics", colour=0x5865F2)
        if filter_by and value:
            embed.description = f"Filtered by **{filter_by.upper()}** = `{value.upper()}`"

        embed.add_field(name="Total Quests",  value=str(total),         inline=True)
        embed.add_field(name="Total Players", value=str(total_players), inline=True)
        embed.add_field(name="By Status",     value=_fmt_counter(status_count),  inline=True)
        embed.add_field(name="By Mode",       value=_fmt_counter(mode_count),    inline=True)
        embed.add_field(name="By Type",       value=_fmt_counter(type_count),    inline=True)
        embed.add_field(
            name="By System (top 10)",
            value=_fmt_counter(Counter(dict(system_count.most_common(10)))),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    # ── /stats clear ──────────────────────────────────────────────────────────
    @stats_group.command(name="clear", description="Clear all quest data for this server. Admin only.")
    @app_commands.describe(confirm="Type CONFIRM to proceed — this cannot be undone.")
    @app_commands.default_permissions(manage_guild=True)
    async def stats_clear(self, interaction: discord.Interaction, confirm: str):
        if confirm != "CONFIRM":
            await interaction.response.send_message(
                "❌ You must type `CONFIRM` exactly to clear stats.", ephemeral=True
            )
            return

        cleared = storage.clear_guild_quests(interaction.guild_id)
        await interaction.response.send_message(
            f"🗑️ Cleared **{cleared}** quest(s) from this server's records.", ephemeral=True
        )
