"""
Quest cog — handles /quest command group and the persistent recruit embed.
"""

import os
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from utils import storage, parser
from utils.embeds import build_quest_embed


# ── Persistent Recruit View ────────────────────────────────────────────────────

class RecruitView(discord.ui.View):
    """Persistent View with Join / Leave buttons for a quest."""

    def __init__(self, quest_id: str, max_players: int = 0):
        # timeout=None makes it persistent across restarts (bot must re-add it)
        super().__init__(timeout=None)
        self.quest_id   = quest_id
        self.max_players = max_players
        # Give the buttons custom_ids so Discord can route interactions after restart
        self.add_item(JoinButton(quest_id))
        self.add_item(LeaveButton(quest_id))


class JoinButton(discord.ui.Button):
    def __init__(self, quest_id: str):
        super().__init__(
            label="⚔️ Join Quest",
            style=discord.ButtonStyle.success,
            custom_id=f"quest_join:{quest_id}",
        )
        self.quest_id = quest_id

    async def callback(self, interaction: discord.Interaction):
        quest = storage.get_quest(self.quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        if quest["status"] in ("COMPLETED", "CANCELLED"):
            await interaction.response.send_message(
                f"❌ This quest is `{quest['status']}` and no longer accepting players.", ephemeral=True
            )
            return

        uid = str(interaction.user.id)
        roster   = quest.get("roster", [])
        waitlist = quest.get("waitlist", [])
        max_p    = quest.get("max_players", 0)

        if uid in roster:
            await interaction.response.send_message("You're already in the roster!", ephemeral=True)
            return
        if uid in waitlist:
            await interaction.response.send_message("You're already on the waitlist!", ephemeral=True)
            return

        if max_p and len(roster) >= max_p:
            waitlist.append(uid)
            quest["waitlist"] = waitlist
            storage.save_quest(self.quest_id, quest)
            await interaction.response.send_message(
                f"The quest is full! You've been added to the **waitlist** (position {len(waitlist)}).", ephemeral=True
            )
        else:
            roster.append(uid)
            quest["roster"] = roster
            # Update status to FULL if capped
            if max_p and len(roster) >= max_p:
                quest["status"] = "FULL"
            storage.save_quest(self.quest_id, quest)
            await interaction.response.send_message("✅ You've joined the quest!", ephemeral=True)

        await _sync_quest_everywhere(interaction.client, self.quest_id, quest)


class LeaveButton(discord.ui.Button):
    def __init__(self, quest_id: str):
        super().__init__(
            label="🚪 Leave Quest",
            style=discord.ButtonStyle.danger,
            custom_id=f"quest_leave:{quest_id}",
        )
        self.quest_id = quest_id

    async def callback(self, interaction: discord.Interaction):
        quest = storage.get_quest(self.quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        roster   = quest.get("roster", [])
        waitlist = quest.get("waitlist", [])
        max_p    = quest.get("max_players", 0)

        if uid in roster:
            roster.remove(uid)
            # Promote first person on waitlist
            if waitlist:
                promoted = waitlist.pop(0)
                roster.append(promoted)
                try:
                    user = await interaction.client.fetch_user(int(promoted))
                    await interaction.followup.send(
                        f"<@{promoted}> has been promoted from the waitlist!", ephemeral=False
                    )
                except Exception:
                    pass
            # Re-open status if was FULL
            if quest["status"] == "FULL":
                quest["status"] = "RECRUITING"
            quest["roster"]   = roster
            quest["waitlist"] = waitlist
            storage.save_quest(self.quest_id, quest)
            await interaction.response.send_message("You've left the quest.", ephemeral=True)
            await _sync_quest_everywhere(interaction.client, self.quest_id, quest)

        elif uid in waitlist:
            waitlist.remove(uid)
            quest["waitlist"] = waitlist
            storage.save_quest(self.quest_id, quest)
            await interaction.response.send_message("You've been removed from the waitlist.", ephemeral=True)
            await _sync_quest_everywhere(interaction.client, self.quest_id, quest)
        else:
            await interaction.response.send_message("You're not in this quest.", ephemeral=True)


# ── Helper: sync embed + thread title ─────────────────────────────────────────

async def _sync_quest_everywhere(bot: discord.Client, quest_id: str, quest: dict):
    """Update the embed message and thread title to reflect current quest state."""
    embed_ch_id  = quest.get("embed_channel_id")
    embed_msg_id = quest.get("embed_message_id")
    thread_id    = quest.get("thread_id")

    # Update embed
    if embed_ch_id and embed_msg_id:
        try:
            channel = bot.get_channel(embed_ch_id) or await bot.fetch_channel(embed_ch_id)
            msg     = await channel.fetch_message(embed_msg_id)
            thread_url = _make_thread_url(quest)
            embed = build_quest_embed(quest, thread_url)
            await msg.edit(embed=embed)
        except Exception as e:
            print(f"[WARN] Could not update embed: {e}")

    # Update thread title
    if thread_id:
        try:
            thread = bot.get_channel(thread_id) or await bot.fetch_channel(thread_id)
            new_title = parser.build_thread_title(quest)
            if thread.name != new_title:
                await thread.edit(name=new_title)
        except Exception as e:
            print(f"[WARN] Could not update thread title: {e}")


def _make_thread_url(quest: dict) -> str:
    guild_id  = quest.get("guild_id", 0)
    thread_id = quest.get("thread_id", 0)
    return f"https://discord.com/channels/{guild_id}/{thread_id}"


# ── Cog ───────────────────────────────────────────────────────────────────────

class QuestCog(commands.Cog):
    """All /quest commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._re_add_views()

    def _re_add_views(self):
        """Re-register all persistent views on startup so buttons still work."""
        all_quests = storage.get_all_quests()
        for quest_id, quest in all_quests.items():
            if quest.get("status") not in ("COMPLETED", "CANCELLED"):
                self.bot.add_view(RecruitView(quest_id=quest_id, max_players=quest.get("max_players", 0)))

    quest = app_commands.Group(name="quest", description="Quest Board management commands")

    # ── /quest recruit ────────────────────────────────────────────────────────
    @quest.command(name="recruit", description="Post a persistent recruitment embed for a quest.")
    @app_commands.describe(
        thread="The quest forum thread",
        max_players="Maximum roster size (0 = unlimited)",
    )
    async def quest_recruit(
        self,
        interaction: discord.Interaction,
        thread: discord.Thread,
        max_players: int = 0,
    ):
        await interaction.response.defer(ephemeral=True)

        # Load guild config — require /setup to have been run first
        config = storage.get_guild_config(interaction.guild_id)
        embed_channel_id = config.get("embed_channel_id")
        if not embed_channel_id:
            await interaction.followup.send(
                "❌ The Quest Board hasn't been configured yet. Ask an admin to run `/setup` first.",
                ephemeral=True,
            )
            return
        embed_channel = interaction.guild.get_channel(embed_channel_id)
        if not embed_channel:
            await interaction.followup.send(
                "❌ The configured embed channel no longer exists. Ask an admin to run `/setup` again.",
                ephemeral=True,
            )
            return
        existing = storage.get_quest_by_thread(thread.id)
        if existing:
            await interaction.followup.send(
                f"❌ A quest embed already exists for that thread (`{existing['quest_id']}`).", ephemeral=True
            )
            return

        # Parse thread
        parsed  = parser.parse_title(thread.name)
        quest_id = storage.generate_quest_id()

        # Try to detect system from first message if not in title
        system = parsed["system"]
        if not system:
            try:
                async for msg in thread.history(limit=1, oldest_first=True):
                    system = parser.parse_system_from_body(msg.content)
            except Exception:
                pass

        quest = {
            "quest_id":        quest_id,
            "guild_id":        interaction.guild_id,
            "thread_id":       thread.id,
            "dm_id":           str(interaction.user.id),
            "title":           parsed["title"],
            "status":          parsed["status"] or "RECRUITING",
            "mode":            parsed["mode"],
            "quest_type":      parsed["quest_type"],
            "system":          system,
            "max_players":     max_players,
            "roster":          [],
            "waitlist":        [],
            "embed_channel_id": embed_channel.id,
            "embed_message_id": None,
        }

        # If system still unknown, ask DM quietly
        if not system:
            try:
                dm_user = interaction.user
                await dm_user.send(
                    f"👋 Hey! Your quest **{quest['title']}** (`{quest_id}`) is missing a game system. "
                    f"Please reply to the thread with the system name (e.g. D&D 5e, Pathfinder 2e, etc.) "
                    f"or update the thread title with `[SYSTEM]`."
                )
            except Exception:
                pass
            quest["system"] = "UNKNOWN"

        storage.save_quest(quest_id, quest)

        # Build and post embed
        thread_url = _make_thread_url(quest)
        embed = build_quest_embed(quest, thread_url)
        view  = RecruitView(quest_id=quest_id, max_players=max_players)
        self.bot.add_view(view)

        # Ping roles based on quest mode and type from /setup config
        ping_ids = []
        if quest.get("mode") == "ONLINE"    and config.get("ping_role_online"):
            ping_ids.append(config["ping_role_online"])
        if quest.get("mode") == "OFFLINE"   and config.get("ping_role_offline"):
            ping_ids.append(config["ping_role_offline"])
        if quest.get("quest_type") == "ONESHOT"  and config.get("ping_role_oneshot"):
            ping_ids.append(config["ping_role_oneshot"])
        if quest.get("quest_type") == "CAMPAIGN" and config.get("ping_role_campaign"):
            ping_ids.append(config["ping_role_campaign"])
        ping_content = " ".join(f"<@&{rid}>" for rid in ping_ids) or None

        sent = await embed_channel.send(content=ping_content, embed=embed, view=view)

        quest["embed_message_id"] = sent.id
        storage.save_quest(quest_id, quest)

        # Sync thread title to canonical format
        new_title = parser.build_thread_title(quest)
        try:
            await thread.edit(name=new_title)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Quest `{quest_id}` posted in {embed_channel.mention}!", ephemeral=True
        )

    # ── /quest complete ───────────────────────────────────────────────────────
    @quest.command(name="complete", description="Mark a quest as COMPLETED.")
    @app_commands.describe(quest_id="The Quest ID (e.g. 230224-0001)")
    async def quest_complete(self, interaction: discord.Interaction, quest_id: str):
        await self._set_status(interaction, quest_id, "COMPLETED")

    # ── /quest cancel ─────────────────────────────────────────────────────────
    @quest.command(name="cancel", description="Mark a quest as CANCELLED.")
    @app_commands.describe(quest_id="The Quest ID (e.g. 230224-0001)")
    async def quest_cancel(self, interaction: discord.Interaction, quest_id: str):
        await self._set_status(interaction, quest_id, "CANCELLED")

    # ── /quest info ───────────────────────────────────────────────────────────
    @quest.command(name="info", description="Show information about a specific quest.")
    @app_commands.describe(quest_id="The Quest ID (e.g. 230224-0001)")
    async def quest_info(self, interaction: discord.Interaction, quest_id: str):
        quest = storage.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return
        quest["quest_id"] = quest_id
        thread_url = _make_thread_url(quest)
        embed = build_quest_embed(quest, thread_url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /quest update ─────────────────────────────────────────────────────────
    @quest.command(name="update", description="Manually update quest parameters.")
    @app_commands.describe(
        quest_id="The Quest ID",
        status="New status",
        mode="Online or Offline",
        quest_type="Oneshot or Campaign",
        system="Game system",
        max_players="Max roster size (0 = unlimited)",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="RECRUITING", value="RECRUITING"),
            app_commands.Choice(name="FULL",       value="FULL"),
            app_commands.Choice(name="COMPLETED",  value="COMPLETED"),
            app_commands.Choice(name="CANCELLED",  value="CANCELLED"),
        ],
        mode=[
            app_commands.Choice(name="ONLINE",  value="ONLINE"),
            app_commands.Choice(name="OFFLINE", value="OFFLINE"),
        ],
        quest_type=[
            app_commands.Choice(name="ONESHOT",   value="ONESHOT"),
            app_commands.Choice(name="CAMPAIGN",  value="CAMPAIGN"),
        ],
    )
    async def quest_update(
        self,
        interaction: discord.Interaction,
        quest_id: str,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        quest_type: Optional[str] = None,
        system: Optional[str] = None,
        max_players: Optional[int] = None,
    ):
        quest = storage.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        if status:     quest["status"]     = status.upper()
        if mode:       quest["mode"]       = mode.upper()
        if quest_type: quest["quest_type"] = quest_type.upper()
        if system:     quest["system"]     = system.upper()
        if max_players is not None:
            quest["max_players"] = max_players

        quest["quest_id"] = quest_id
        storage.save_quest(quest_id, quest)
        await _sync_quest_everywhere(self.bot, quest_id, quest)
        await interaction.response.send_message(f"✅ Quest `{quest_id}` updated.", ephemeral=True)

    # ── Internal helpers ──────────────────────────────────────────────────────
    async def _set_status(self, interaction: discord.Interaction, quest_id: str, new_status: str):
        quest = storage.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        # Only DM or server admins may change status
        is_dm    = str(interaction.user.id) == quest.get("dm_id")
        is_admin = interaction.user.guild_permissions.manage_channels
        if not (is_dm or is_admin):
            await interaction.response.send_message(
                "❌ Only the Quest DM or an admin can change this quest's status.", ephemeral=True
            )
            return

        quest["status"]   = new_status
        quest["quest_id"] = quest_id
        storage.save_quest(quest_id, quest)
        await _sync_quest_everywhere(self.bot, quest_id, quest)
        await interaction.response.send_message(
            f"✅ Quest `{quest_id}` marked as `{new_status}`.", ephemeral=True
        )
