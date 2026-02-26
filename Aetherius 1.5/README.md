# ⚔️ Quest Board Bot

A Discord bot for managing a TTRPG forum Quest Board. It automatically parses quest parameters from thread titles, posts persistent recruitment embeds with Join/Leave buttons, tracks rosters and waitlists, and keeps everything in sync.

---

## Project Structure

```
questboard-bot/
├── bot.py                  # Entry point — creates and runs the bot
├── requirements.txt
├── .env.example            # Copy to .env and fill in your values
├── data/
│   └── quests.json         # Auto-created persistent storage
├── cogs/
│   ├── quest.py            # /quest command group + persistent recruit view
│   ├── stats.py            # /stats command
│   └── forum_listener.py   # Auto-detects new forum threads
└── utils/
    ├── storage.py          # JSON-based persistence layer
    ├── parser.py           # Title/body parsing, thread title builder
    └── embeds.py           # Discord embed factory
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your values
```

| Variable           | Required | Description                                                     |
|--------------------|----------|-----------------------------------------------------------------|
| `DISCORD_TOKEN`    | ✅       | Your bot token from the Discord Developer Portal               |
| `GUILD_ID`         | Optional | Your server ID for faster slash command syncing                 |
| `FORUM_CHANNEL_ID` | Optional | The forum channel to auto-listen for new quest threads          |

### 3. Discord Developer Portal settings
Enable the following **Privileged Gateway Intents** in your bot's settings:
- **Server Members Intent**
- **Message Content Intent**

### 4. Run the bot
```bash
python bot.py
```

---

## Quest Parameters

| Parameter       | Format / Values                             |
|-----------------|---------------------------------------------|
| `[Quest_ID]`    | `[ddmmyy-xxxx]` — auto-generated            |
| `[Quest_Status]`| `RECRUITING` / `FULL` / `COMPLETED` / `CANCELLED` |
| `[Quest_Mode]`  | `ONLINE` / `OFFLINE`                        |
| `[Quest_Type]`  | `ONESHOT` / `CAMPAIGN`                      |
| `[Quest_System]`| Any ruleset name (parsed from title or body)|
| `[Quest_DM]`    | The user who created / ran `/quest recruit` |
| `<Quest_Title>` | Everything in the title outside brackets    |

### Thread title format
```
[STATUS] [MODE] [TYPE] [SYSTEM] Quest Title
```
**Example:** `[RECRUITING] [OFFLINE] [ONESHOT] [D&D] Star of Omens`

The bot keeps the thread title in this canonical format at all times.

---

## Commands

### `/quest recruit`
Posts a persistent recruitment embed with **Join** and **Leave** buttons.

| Option          | Description                                      |
|-----------------|--------------------------------------------------|
| `thread`        | The forum quest thread                           |
| `embed_channel` | Channel where the embed will be posted           |
| `max_players`   | Roster cap (0 = unlimited)                       |
| `ping_role`     | Role to ping when the embed is posted (optional) |

- Players beyond `max_players` are automatically moved to a **Waitlist**.
- When a player leaves, the first person on the waitlist is promoted.
- `[Quest_Status]` updates automatically: `RECRUITING` → `FULL` and back.

---

### `/quest complete <quest_id>`
Marks the quest `[COMPLETED]`. Only the DM or a server admin can use this.

### `/quest cancel <quest_id>`
Marks the quest `[CANCELLED]`. Only the DM or a server admin can use this.

### `/quest info <quest_id>`
Displays current quest information ephemerally.

### `/quest update <quest_id> [options]`
Manually update one or more parameters of a quest.

| Option        | Description          |
|---------------|----------------------|
| `status`      | New status           |
| `mode`        | ONLINE / OFFLINE     |
| `quest_type`  | ONESHOT / CAMPAIGN   |
| `system`      | Game system name     |
| `max_players` | New roster cap       |

---

### `/stats [filter_by] [value]`
Shows aggregated Quest Board statistics.

| Option      | Description                                            |
|-------------|--------------------------------------------------------|
| `filter_by` | `status`, `mode`, `quest_type`, or `system`            |
| `value`     | The specific value to filter by (e.g. `D&D`, `ONLINE`) |

---

## Automatic Forum Thread Detection

If `FORUM_CHANNEL_ID` is set, the bot listens for new threads in the forum and:

1. Parses the title and starter message for quest parameters.
2. Assigns a `Quest_ID` and saves the quest to the database.
3. Renames the thread to the canonical format.
4. **If the system can't be determined**, quietly DMs the thread creator and asks them to specify it.

After auto-detection, run `/quest recruit` to post the public embed.

---

## Data Storage

Quests are stored in `data/quests.json`. The file is created automatically on first run. No external database is needed.

---

## Bot Permissions Required

| Permission          | Reason                                       |
|---------------------|----------------------------------------------|
| Read Messages       | Read forum threads                           |
| Send Messages       | Post embeds and DMs                          |
| Embed Links         | Render quest embeds                          |
| Manage Threads      | Rename forum threads                        |
| Use Application Commands | Slash commands                        |
| Mention Roles       | Ping roles when posting embeds               |
