"""
Forum Listener cog — watches the designated forum channel for new threads
and automatically posts a recruitment embed as soon as one is created.
"""

import discord
from discord.ext import commands

from utils import storage, parser
from utils.embeds import build_quest_embed
from cogs.quest import RecruitView, _make_thread_url


class ForumListenerCog(commands.Cog):
    """Listens to the forum channel and auto-posts quest embeds on thread creation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Fires when a new thread is created anywhere in the guild."""
        # Load guild config and check if this thread is in the configured forum
        config = storage.get_guild_config(thread.guild.id)
        forum_channel_id = config.get("forum_channel_id")

        if not forum_channel_id or thread.parent_id != forum_channel_id:
            return

        # Wait briefly for the starter message to arrive
        await discord.utils.sleep_until(
            discord.utils.utcnow().replace(microsecond=0)
        )

        # Parse the title
        parsed = parser.parse_title(thread.name)
        system = parsed["system"]

        # Try to detect system from the starter message body
        starter_body = ""
        try:
            async for msg in thread.history(limit=1, oldest_first=True):
                starter_body = msg.content
        except Exception:
            pass

        if not system and starter_body:
            system = parser.parse_system_from_body(starter_body)

        embed_channel_id = config.get("embed_channel_id")
        quest_id = storage.generate_quest_id()

        quest = {
            "quest_id":          quest_id,
            "guild_id":          thread.guild.id,
            "thread_id":         thread.id,
            "dm_id":             str(thread.owner_id),
            "title":             parsed["title"],
            "status":            parsed["status"] or "RECRUITING",
            "mode":              parsed["mode"],
            "quest_type":        parsed["quest_type"],
            "system":            system,
            "max_players":       0,
            "roster":            [],
            "waitlist":          [],
            "embed_channel_id":  embed_channel_id,
            "embed_message_id":  None,
        }

        storage.save_quest(quest_id, quest)

        # Rename thread to canonical format
        new_title = parser.build_thread_title(quest)
        try:
            if thread.name != new_title:
                await thread.edit(name=new_title)
        except Exception:
            pass

        # Post the embed if an embed channel is configured
        if embed_channel_id:
            embed_channel = thread.guild.get_channel(embed_channel_id)
            if embed_channel:
                thread_url = _make_thread_url(quest)
                embed = build_quest_embed(quest, thread_url)
                view = RecruitView(quest_id=quest_id, max_players=0)
                self.bot.add_view(view)

                # Build pings from config based on quest mode and type
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

        # If system couldn't be determined, quietly DM the thread creator
        if not system:
            quest["system"] = "UNKNOWN"
            storage.save_quest(quest_id, quest)
            try:
                owner = await self.bot.fetch_user(thread.owner_id)
                await owner.send(
                    f"👋 Hi! Your quest **{quest['title']}** (`{quest_id}`) was posted to the Quest Board, "
                    f"but the game system couldn't be determined from the title or post.\n\n"
                    f"Please mention the system in your quest post (e.g. *D&D 5e*, *Pathfinder 2e*) "
                    f"or include it in the thread title like `[D&D]`. "
                    f"Then use `/quest update quest_id:{quest_id} system:<n>` to update the record."
                )
            except Exception:
                pass
