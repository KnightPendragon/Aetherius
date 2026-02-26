"""
Build Discord embeds for Quest Board posts.
"""

import discord
from utils.parser import status_colour

MAX_ROSTER = int.__new__(int)   # resolved at runtime from config


def build_quest_embed(quest: dict, thread_url: str) -> discord.Embed:
    """Build the main quest info embed."""
    status   = quest.get("status", "RECRUITING")
    colour   = status_colour(status)

    embed = discord.Embed(
        title=f"📜 {quest.get('title', 'Untitled Quest')}",
        colour=colour,
        url=thread_url,
    )

    embed.add_field(name="Quest ID",  value=f"`{quest['quest_id']}`",          inline=True)
    embed.add_field(name="Status",    value=f"`{status}`",                      inline=True)
    embed.add_field(name="Mode",      value=f"`{quest.get('mode','—')}`",       inline=True)
    embed.add_field(name="Type",      value=f"`{quest.get('quest_type','—')}`", inline=True)
    embed.add_field(name="System",    value=f"`{quest.get('system','—')}`",     inline=True)
    embed.add_field(name="DM",        value=f"<@{quest['dm_id']}>",             inline=True)

    # Roster
    roster = quest.get("roster", [])
    waitlist = quest.get("waitlist", [])
    max_players = quest.get("max_players", 0)

    roster_str = "\n".join(f"<@{uid}>" for uid in roster) if roster else "*No players yet.*"
    embed.add_field(
        name=f"Roster ({len(roster)}/{max_players if max_players else '∞'})",
        value=roster_str,
        inline=False,
    )

    if waitlist:
        wl_str = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(waitlist))
        embed.add_field(name="Waitlist", value=wl_str, inline=False)

    embed.add_field(name="🔗 Quest Thread", value=f"[Jump to Quest]({thread_url})", inline=False)
    embed.set_footer(text=f"Quest ID: {quest['quest_id']}")

    return embed


def build_recruit_view(quest: dict, max_players: int = 0) -> discord.ui.View:
    """Return a persistent View with Join / Leave buttons."""
    from cogs.quest import RecruitView
    return RecruitView(quest_id=quest["quest_id"], max_players=max_players)
