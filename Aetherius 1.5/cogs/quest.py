"""
Quest cog — handles /quest command group and the persistent recruit embed.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from typing import Optional

from utils import storage, parser
from utils.embeds import build_quest_embed


# ── Permission helper ──────────────────────────────────────────────────────────

def _is_quest_manager(interaction: discord.Interaction, quest: dict) -> bool:
    """Returns True if the user is the quest's DM or a server admin."""
    is_dm    = str(interaction.user.id) == quest.get("dm_id")
    is_admin = interaction.user.guild_permissions.manage_guild
    return is_dm or is_admin


# ── Application rate limiter (in-memory, 3 per user per hour per quest) ────────

# { (user_id, quest_id): [timestamp, ...] }
_apply_timestamps: dict[tuple, list] = {}

APPLICATION_LIMIT    = 3
APPLICATION_WINDOW   = 3600  # seconds


def _check_apply_rate(user_id: str, quest_id: str) -> tuple[bool, int]:
    """
    Returns (allowed, seconds_until_reset).
    Cleans up old timestamps outside the window.
    """
    now  = datetime.now(timezone.utc).timestamp()
    key  = (user_id, quest_id)
    times = _apply_timestamps.get(key, [])
    times = [t for t in times if now - t < APPLICATION_WINDOW]
    _apply_timestamps[key] = times

    if len(times) >= APPLICATION_LIMIT:
        reset_in = int(APPLICATION_WINDOW - (now - times[0]))
        return False, reset_in

    times.append(now)
    _apply_timestamps[key] = times
    return True, 0


# ── Accept / Decline view (sent to DM) ────────────────────────────────────────

class ApplicationView(discord.ui.View):
    """Non-persistent view sent to the DM's inbox to accept or decline an applicant."""

    def __init__(self, quest_id: str, applicant_id: str):
        super().__init__(timeout=None)
        self.quest_id     = quest_id
        self.applicant_id = applicant_id
        self.add_item(AcceptButton(quest_id, applicant_id))
        self.add_item(DeclineButton(quest_id, applicant_id))


class AcceptButton(discord.ui.Button):
    def __init__(self, quest_id: str, applicant_id: str):
        super().__init__(
            label="✅ Accept",
            style=discord.ButtonStyle.success,
            custom_id=f"app_accept:{quest_id}:{applicant_id}",
        )
        self.quest_id     = quest_id
        self.applicant_id = applicant_id

    async def callback(self, interaction: discord.Interaction):
        quest = storage.get_quest(self.quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest no longer exists.", ephemeral=True)
            return

        quest["quest_id"] = self.quest_id
        roster  = quest.get("roster", [])
        max_p   = quest.get("max_players", 0)

        if self.applicant_id in roster:
            await interaction.response.send_message(
                "This applicant is already on the roster.", ephemeral=True
            )
            self._disable_buttons()
            await interaction.message.edit(view=self.view)
            return

        if max_p and len(roster) >= max_p:
            await interaction.response.send_message(
                "❌ The roster is already full. Decline someone first or increase the player cap.",
                ephemeral=True,
            )
            return

        roster.append(self.applicant_id)
        quest["roster"] = roster
        if max_p and len(roster) >= max_p:
            quest["status"] = "FULL"

        storage.save_quest(self.quest_id, quest)
        await _sync_quest_everywhere(interaction.client, self.quest_id, quest)

        # Disable both buttons on the DM message
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **Accepted** <@{self.applicant_id}> into **{quest.get('title')}**.",
            view=self.view,
        )

        # Notify the applicant
        try:
            applicant = await interaction.client.fetch_user(int(self.applicant_id))
            await applicant.send(
                f"🎉 Your application to **{quest.get('title')}** (`{self.quest_id}`) has been **accepted**!"
            )
        except Exception:
            pass


class DeclineButton(discord.ui.Button):
    def __init__(self, quest_id: str, applicant_id: str):
        super().__init__(
            label="❌ Decline",
            style=discord.ButtonStyle.danger,
            custom_id=f"app_decline:{quest_id}:{applicant_id}",
        )
        self.quest_id     = quest_id
        self.applicant_id = applicant_id

    async def callback(self, interaction: discord.Interaction):
        quest = storage.get_quest(self.quest_id)
        title = quest.get("title", self.quest_id) if quest else self.quest_id

        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"❌ **Declined** <@{self.applicant_id}>'s application for **{title}**.",
            view=self.view,
        )

        # Notify the applicant
        try:
            applicant = await interaction.client.fetch_user(int(self.applicant_id))
            await applicant.send(
                f"😔 Your application to **{title}** (`{self.quest_id}`) was **declined**."
            )
        except Exception:
            pass


# ── Persistent Recruit View ────────────────────────────────────────────────────

class RecruitView(discord.ui.View):
    """Persistent View with Apply / Leave buttons for a quest."""

    def __init__(self, quest_id: str, max_players: int = 0):
        super().__init__(timeout=None)
        self.quest_id    = quest_id
        self.max_players = max_players
        self.add_item(ApplyButton(quest_id))
        self.add_item(LeaveButton(quest_id))


class ApplyButton(discord.ui.Button):
    def __init__(self, quest_id: str):
        super().__init__(
            label="📜 Apply",
            style=discord.ButtonStyle.primary,
            custom_id=f"quest_apply:{quest_id}",
        )
        self.quest_id = quest_id

    async def callback(self, interaction: discord.Interaction):
        quest = storage.get_quest(self.quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        if quest["status"] in ("COMPLETED", "CANCELLED"):
            await interaction.response.send_message(
                f"❌ This quest is `{quest['status']}` and no longer accepting applications.",
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)

        # Don't let the DM apply to their own quest
        if uid == quest.get("dm_id"):
            await interaction.response.send_message(
                "You can't apply to your own quest!", ephemeral=True
            )
            return

        if uid in quest.get("roster", []):
            await interaction.response.send_message(
                "You're already on the roster!", ephemeral=True
            )
            return

        # Rate limit check
        allowed, reset_in = _check_apply_rate(uid, self.quest_id)
        if not allowed:
            minutes = reset_in // 60
            seconds = reset_in % 60
            await interaction.response.send_message(
                f"⏳ You've reached the application limit ({APPLICATION_LIMIT} per hour). "
                f"Try again in **{minutes}m {seconds}s**.",
                ephemeral=True,
            )
            return

        # Send application embed to the DM
        dm_id = quest.get("dm_id")
        try:
            dm_user = await interaction.client.fetch_user(int(dm_id))
            app_embed = discord.Embed(
                title="📋 New Quest Application",
                colour=0xFEE75C,
            )
            app_embed.add_field(name="Quest",       value=f"**{quest.get('title')}** (`{self.quest_id}`)", inline=False)
            app_embed.add_field(name="Applicant",   value=f"<@{uid}>",                                    inline=True)
            app_embed.add_field(name="User ID",     value=f"`{uid}`",                                     inline=True)
            app_embed.add_field(
                name="Applied On",
                value=discord.utils.format_dt(discord.utils.utcnow(), style="F"),
                inline=False,
            )
            app_embed.set_footer(text=f"Quest ID: {self.quest_id}")

            view = ApplicationView(quest_id=self.quest_id, applicant_id=uid)
            interaction.client.add_view(view)

            await dm_user.send(embed=app_embed, view=view)
            await interaction.response.send_message(
                "📨 Your application has been sent to the Quest DM! You'll be notified of the decision.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Could not send a DM to the Quest DM. They may have DMs disabled.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Something went wrong sending your application: {e}", ephemeral=True
            )


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

        uid      = str(interaction.user.id)
        roster   = quest.get("roster", [])
        max_p    = quest.get("max_players", 0)

        if uid in roster:
            roster.remove(uid)
            if quest["status"] == "FULL":
                quest["status"] = "RECRUITING"
            quest["roster"] = roster
            storage.save_quest(self.quest_id, quest)
            await interaction.response.send_message("You've left the quest.", ephemeral=True)
            await _sync_quest_everywhere(interaction.client, self.quest_id, quest)

            # Notify the Quest DM
            try:
                dm_user = await interaction.client.fetch_user(int(quest["dm_id"]))
                await dm_user.send(
                    f"👋 **{interaction.user.display_name}** has left your quest "
                    f"**{quest.get('title')}** (`{self.quest_id}`)."
                )
            except Exception:
                pass
        else:
            await interaction.response.send_message("You're not on the roster.", ephemeral=True)


# ── Helper: sync embed + thread title ─────────────────────────────────────────

async def _sync_quest_everywhere(bot: discord.Client, quest_id: str, quest: dict):
    """Update the embed message and thread title to reflect current quest state."""
    embed_ch_id  = quest.get("embed_channel_id")
    embed_msg_id = quest.get("embed_message_id")
    thread_id    = quest.get("thread_id")

    if embed_ch_id and embed_msg_id:
        try:
            channel    = bot.get_channel(embed_ch_id) or await bot.fetch_channel(embed_ch_id)
            msg        = await channel.fetch_message(embed_msg_id)
            thread_url = _make_thread_url(quest)
            embed      = build_quest_embed(quest, thread_url)
            await msg.edit(embed=embed)
        except Exception as e:
            print(f"[WARN] Could not update embed: {e}")

    if thread_id:
        try:
            thread    = bot.get_channel(thread_id) or await bot.fetch_channel(thread_id)
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
                self.bot.add_view(
                    RecruitView(quest_id=quest_id, max_players=quest.get("max_players", 0))
                )

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

        # Load guild config
        config = storage.get_guild_config(interaction.guild_id)
        embed_channel_id = config.get("embed_channel_id")
        if not embed_channel_id:
            await interaction.followup.send(
                "❌ No embed channel configured. Ask an admin to run `/setup` first.", ephemeral=True
            )
            return
        embed_channel = interaction.guild.get_channel(embed_channel_id)
        if not embed_channel:
            await interaction.followup.send(
                "❌ The configured embed channel no longer exists. Ask an admin to run `/setup` again.",
                ephemeral=True,
            )
            return

        # Permission check — thread owner or admin only
        is_owner = interaction.user.id == thread.owner_id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not (is_owner or is_admin):
            await interaction.followup.send(
                "❌ Only the thread owner or an admin can post a recruitment embed.", ephemeral=True
            )
            return

        # Check if a quest already exists for this thread
        existing = storage.get_quest_by_thread(thread.id)

        if existing:
            # Re-use existing quest data — just post a fresh embed
            quest_id = existing["quest_id"]
            quest    = existing

            # Try to silently delete the old embed if it still exists
            old_ch_id  = quest.get("embed_channel_id")
            old_msg_id = quest.get("embed_message_id")
            if old_ch_id and old_msg_id:
                try:
                    old_ch  = self.bot.get_channel(old_ch_id) or await self.bot.fetch_channel(old_ch_id)
                    old_msg = await old_ch.fetch_message(old_msg_id)
                    await old_msg.delete()
                except Exception:
                    pass  # Old embed already gone — that's fine

            # Point to the new channel
            quest["embed_channel_id"]  = embed_channel.id
            quest["embed_message_id"]  = None
            if max_players:
                quest["max_players"] = max_players

        else:
            # Brand new quest
            parsed   = parser.parse_title(thread.name)
            quest_id = storage.generate_quest_id()

            system = parsed["system"]
            if not system:
                try:
                    async for msg in thread.history(limit=1, oldest_first=True):
                        system = parser.parse_system_from_body(msg.content)
                except Exception:
                    pass

            quest = {
                "quest_id":          quest_id,
                "guild_id":          interaction.guild_id,
                "thread_id":         thread.id,
                "dm_id":             str(interaction.user.id),
                "title":             parsed["title"],
                "status":            parsed["status"] or "RECRUITING",
                "mode":              parsed["mode"],
                "quest_type":        parsed["quest_type"],
                "system":            system,
                "max_players":       max_players,
                "roster":            [],
                "waitlist":          [],
                "embed_channel_id":  embed_channel.id,
                "embed_message_id":  None,
            }

            if not system:
                try:
                    await interaction.user.send(
                        f"👋 Your quest **{quest['title']}** (`{quest_id}`) is missing a game system. "
                        f"Please update the thread title with `[SYSTEM]` or use `/quest update`."
                    )
                except Exception:
                    pass
                quest["system"] = "UNKNOWN"

        storage.save_quest(quest_id, quest)

        thread_url = _make_thread_url(quest)
        embed      = build_quest_embed(quest, thread_url)
        view       = RecruitView(quest_id=quest_id, max_players=max_players)
        self.bot.add_view(view)

        ping_ids = []
        if quest.get("mode") == "ONLINE"         and config.get("ping_role_online"):
            ping_ids.append(config["ping_role_online"])
        if quest.get("mode") == "OFFLINE"        and config.get("ping_role_offline"):
            ping_ids.append(config["ping_role_offline"])
        if quest.get("quest_type") == "ONESHOT"  and config.get("ping_role_oneshot"):
            ping_ids.append(config["ping_role_oneshot"])
        if quest.get("quest_type") == "CAMPAIGN" and config.get("ping_role_campaign"):
            ping_ids.append(config["ping_role_campaign"])
        ping_content = " ".join(f"<@&{rid}>" for rid in ping_ids) or None

        sent = await embed_channel.send(content=ping_content, embed=embed, view=view)
        quest["embed_message_id"] = sent.id
        storage.save_quest(quest_id, quest)

        new_title = parser.build_thread_title(quest)
        try:
            await thread.edit(name=new_title)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Quest `{quest_id}` posted in {embed_channel.mention}!", ephemeral=True
        )

    # ── /quest register ───────────────────────────────────────────────────────
    @quest.command(name="register", description="Register a quest without posting a public embed.")
    @app_commands.describe(
        thread="The quest forum thread",
        max_players="Maximum roster size (0 = unlimited)",
    )
    async def quest_register(
        self,
        interaction: discord.Interaction,
        thread: discord.Thread,
        max_players: int = 0,
    ):
        await interaction.response.defer(ephemeral=True)

        # Permission check
        is_owner = interaction.user.id == thread.owner_id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not (is_owner or is_admin):
            await interaction.followup.send(
                "❌ Only the thread owner or an admin can register a quest.", ephemeral=True
            )
            return

        existing = storage.get_quest_by_thread(thread.id)
        if existing:
            await interaction.followup.send(
                f"❌ This thread is already registered as quest `{existing['quest_id']}`.",
                ephemeral=True,
            )
            return

        parsed   = parser.parse_title(thread.name)
        quest_id = storage.generate_quest_id()

        system = parsed["system"]
        if not system:
            try:
                async for msg in thread.history(limit=1, oldest_first=True):
                    system = parser.parse_system_from_body(msg.content)
            except Exception:
                pass

        quest = {
            "quest_id":          quest_id,
            "guild_id":          interaction.guild_id,
            "thread_id":         thread.id,
            "dm_id":             str(interaction.user.id),
            "title":             parsed["title"],
            "status":            parsed["status"] or "RECRUITING",
            "mode":              parsed["mode"],
            "quest_type":        parsed["quest_type"],
            "system":            system or "UNKNOWN",
            "max_players":       max_players,
            "roster":            [],
            "waitlist":          [],
            "embed_channel_id":  None,
            "embed_message_id":  None,
        }

        storage.save_quest(quest_id, quest)

        new_title = parser.build_thread_title(quest)
        try:
            await thread.edit(name=new_title)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Quest `{quest_id}` registered. No public embed was posted.\n"
            f"Use `/quest recruit` to post an embed whenever you're ready.",
            ephemeral=True,
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

    # ── /quest kick ───────────────────────────────────────────────────────────
    @quest.command(name="kick", description="Remove a user from the quest roster.")
    @app_commands.describe(
        quest_id="The Quest ID (e.g. 230224-0001)",
        user="The user to remove from the roster",
    )
    async def quest_kick(
        self,
        interaction: discord.Interaction,
        quest_id: str,
        user: discord.Member,
    ):
        quest = storage.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        quest["quest_id"] = quest_id
        if not _is_quest_manager(interaction, quest):
            await interaction.response.send_message(
                "❌ Only the Quest DM or an admin can kick users from a quest.", ephemeral=True
            )
            return

        uid    = str(user.id)
        roster = quest.get("roster", [])

        if uid not in roster:
            await interaction.response.send_message(
                f"❌ {user.mention} is not on the roster.", ephemeral=True
            )
            return

        roster.remove(uid)
        if quest["status"] == "FULL":
            quest["status"] = "RECRUITING"
        quest["roster"] = roster
        storage.save_quest(quest_id, quest)
        await _sync_quest_everywhere(self.bot, quest_id, quest)

        # Notify the kicked user
        try:
            await user.send(
                f"😔 You have been removed from the roster of "
                f"**{quest.get('title')}** (`{quest_id}`)."
            )
        except Exception:
            pass

        await interaction.response.send_message(
            f"✅ {user.mention} has been removed from the roster of `{quest_id}`.",
            ephemeral=True,
        )

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
            app_commands.Choice(name="ONESHOT",  value="ONESHOT"),
            app_commands.Choice(name="CAMPAIGN", value="CAMPAIGN"),
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

        quest["quest_id"] = quest_id
        if not _is_quest_manager(interaction, quest):
            await interaction.response.send_message(
                "❌ Only the Quest DM or an admin can update this quest.", ephemeral=True
            )
            return

        if status:     quest["status"]     = status.upper()
        if mode:       quest["mode"]       = mode.upper()
        if quest_type: quest["quest_type"] = quest_type.upper()
        if system:     quest["system"]     = system.upper()
        if max_players is not None:
            quest["max_players"] = max_players

        storage.save_quest(quest_id, quest)
        await _sync_quest_everywhere(self.bot, quest_id, quest)
        await interaction.response.send_message(f"✅ Quest `{quest_id}` updated.", ephemeral=True)

    # ── /quest delete ────────────────────────────────────────────────────────
    @quest.command(name="delete", description="Delete a quest from the database.")
    @app_commands.describe(quest_id="The Quest ID (e.g. 230224-0001)")
    async def quest_delete(self, interaction: discord.Interaction, quest_id: str):
        quest = storage.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        quest["quest_id"] = quest_id
        if not _is_quest_manager(interaction, quest):
            await interaction.response.send_message(
                "❌ Only the Quest DM or an admin can delete a quest.", ephemeral=True
            )
            return

        # Update embed to show [DELETED] before removing from storage
        embed_ch_id  = quest.get("embed_channel_id")
        embed_msg_id = quest.get("embed_message_id")
        if embed_ch_id and embed_msg_id:
            try:
                quest["status"] = "DELETED"
                channel    = self.bot.get_channel(embed_ch_id) or await self.bot.fetch_channel(embed_ch_id)
                msg        = await channel.fetch_message(embed_msg_id)
                thread_url = _make_thread_url(quest)
                embed      = build_quest_embed(quest, thread_url)
                # Disable all buttons on the embed
                view = discord.ui.View()
                await msg.edit(embed=embed, view=view)
            except Exception as e:
                print(f"[WARN] Could not update embed on delete: {e}")

        # Update thread title to reflect DELETED status
        thread_id = quest.get("thread_id")
        if thread_id:
            try:
                quest["status"] = "DELETED"
                thread    = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)
                new_title = parser.build_thread_title(quest)
                if thread.name != new_title:
                    await thread.edit(name=new_title)
            except Exception as e:
                print(f"[WARN] Could not update thread title on delete: {e}")

        # Remove from storage
        storage.delete_quest(quest_id)

        await interaction.response.send_message(
            f"🗑️ Quest `{quest_id}` has been deleted.", ephemeral=True
        )


    # ── /quest list ───────────────────────────────────────────────────────────
    @quest.command(name="list", description="Browse all registered quests with pagination.")
    async def quest_list(self, interaction: discord.Interaction):
        from cogs.stats import _get_guild_quests, _build_quest_list_embed, QuestListView

        quests = _get_guild_quests(interaction.guild_id)
        if not quests:
            await interaction.response.send_message(
                "📭 No quests have been registered on this server yet.", ephemeral=True
            )
            return

        total_pages = max(1, -(-len(quests) // 10))
        embed = _build_quest_list_embed(quests, 0, total_pages)
        view  = QuestListView(quests=quests, interaction=interaction)
        await interaction.response.send_message(embed=embed, view=view)

    # ── Internal helpers ──────────────────────────────────────────────────────
    async def _set_status(self, interaction: discord.Interaction, quest_id: str, new_status: str):
        quest = storage.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
            return

        quest["quest_id"] = quest_id
        if not _is_quest_manager(interaction, quest):
            await interaction.response.send_message(
                "❌ Only the Quest DM or an admin can change this quest's status.", ephemeral=True
            )
            return

        quest["status"] = new_status
        storage.save_quest(quest_id, quest)
        await _sync_quest_everywhere(self.bot, quest_id, quest)
        await interaction.response.send_message(
            f"✅ Quest `{quest_id}` marked as `{new_status}`.", ephemeral=True
        )
