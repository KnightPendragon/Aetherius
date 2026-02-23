"""
Setup cog — /setup command for server admins to configure the Quest Board.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from utils import storage


class SetupCog(commands.Cog):
    """Server configuration for the Quest Board."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Configure the Quest Board for this server.")
    @app_commands.describe(
        forum_channel="The forum channel used as the Quest Board",
        embed_channel="Channel where all quest embeds will be posted",
        ping_role_online="Role to ping for ONLINE quests (optional)",
        ping_role_offline="Role to ping for OFFLINE quests (optional)",
        ping_role_oneshot="Role to ping for ONESHOT quests (optional)",
        ping_role_campaign="Role to ping for CAMPAIGN quests (optional)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        forum_channel: discord.ForumChannel,
        embed_channel: discord.TextChannel,
        ping_role_online: Optional[discord.Role] = None,
        ping_role_offline: Optional[discord.Role] = None,
        ping_role_oneshot: Optional[discord.Role] = None,
        ping_role_campaign: Optional[discord.Role] = None,
    ):
        config = {
            "forum_channel_id":    forum_channel.id,
            "embed_channel_id":    embed_channel.id,
            "ping_role_online":    ping_role_online.id  if ping_role_online  else None,
            "ping_role_offline":   ping_role_offline.id if ping_role_offline else None,
            "ping_role_oneshot":   ping_role_oneshot.id if ping_role_oneshot else None,
            "ping_role_campaign":  ping_role_campaign.id if ping_role_campaign else None,
        }
        storage.save_guild_config(interaction.guild_id, config)

        def role_str(role_id):
            return f"<@&{role_id}>" if role_id else "*None*"

        embed = discord.Embed(
            title="✅ Quest Board Configured",
            description="These settings will be used automatically for all future quest embeds.",
            colour=0x57F287,
        )
        embed.add_field(name="Forum Channel",  value=forum_channel.mention,                   inline=False)
        embed.add_field(name="Embed Channel",  value=embed_channel.mention,                   inline=False)
        embed.add_field(name="Ping: ONLINE",   value=role_str(config["ping_role_online"]),    inline=True)
        embed.add_field(name="Ping: OFFLINE",  value=role_str(config["ping_role_offline"]),   inline=True)
        embed.add_field(name="Ping: ONESHOT",  value=role_str(config["ping_role_oneshot"]),   inline=True)
        embed.add_field(name="Ping: CAMPAIGN", value=role_str(config["ping_role_campaign"]),  inline=True)
        embed.set_footer(text="Use /setup again at any time to update these settings.")

        await interaction.response.send_message(embed=embed)