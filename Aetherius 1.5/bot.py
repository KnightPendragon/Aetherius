import discord
from discord.ext import commands
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("questboard")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True


class QuestBoard(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        from cogs.quest import QuestCog
        from cogs.stats import StatsCog
        from cogs.forum_listener import ForumListenerCog
        from cogs.setup import SetupCog

        await self.add_cog(QuestCog(self))
        await self.add_cog(StatsCog(self))
        await self.add_cog(ForumListenerCog(self))
        await self.add_cog(SetupCog(self))

        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Synced slash commands to guild {guild_id}")
        else:
            await self.tree.sync()
            log.info("Synced slash commands globally")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN not set in environment.")
    bot = QuestBoard()
    bot.run(token)


if __name__ == "__main__":
    main()
