"""
Simple JSON-based persistent storage for quests.
Stores data in data/quests.json relative to the project root.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_PATH = Path(__file__).parent.parent / "data" / "quests.json"
_lock = threading.Lock()


def _load() -> dict:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_PATH.exists():
        return {"quests": {}, "daily_counter": {}}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_quest_id() -> str:
    """Generate a unique Quest ID in format ddmmyy-xxxx."""
    with _lock:
        data = _load()
        now = datetime.now(timezone.utc)
        date_key = now.strftime("%d%m%y")

        counters = data.get("daily_counter", {})
        current = counters.get(date_key, 0) + 1
        counters[date_key] = current
        data["daily_counter"] = counters

        _save(data)
        return f"{date_key}-{str(current).zfill(4)}"


def save_quest(quest_id: str, quest_data: dict):
    with _lock:
        data = _load()
        data["quests"][quest_id] = quest_data
        _save(data)


def get_quest(quest_id: str) -> Optional[dict]:
    with _lock:
        data = _load()
        return data["quests"].get(quest_id)


def get_quest_by_thread(thread_id: int) -> Optional[dict]:
    with _lock:
        data = _load()
        for quest_id, quest in data["quests"].items():
            if quest.get("thread_id") == thread_id:
                return {**quest, "quest_id": quest_id}
        return None


def get_quest_by_embed_message(message_id: int) -> Optional[dict]:
    with _lock:
        data = _load()
        for quest_id, quest in data["quests"].items():
            if quest.get("embed_message_id") == message_id:
                return {**quest, "quest_id": quest_id}
        return None


def get_all_quests() -> dict:
    with _lock:
        data = _load()
        return data["quests"]


def delete_quest(quest_id: str):
    with _lock:
        data = _load()
        data["quests"].pop(quest_id, None)
        _save(data)


def get_guild_config(guild_id: int) -> dict:
    with _lock:
        data = _load()
        return data.get("guild_configs", {}).get(str(guild_id), {})


def save_guild_config(guild_id: int, config: dict):
    with _lock:
        data = _load()
        if "guild_configs" not in data:
            data["guild_configs"] = {}
        data["guild_configs"][str(guild_id)] = config
        _save(data)


def clear_guild_quests(guild_id: int) -> int:
    """Delete all quests belonging to a guild. Returns the number of quests deleted."""
    with _lock:
        data = _load()
        before = len(data["quests"])
        data["quests"] = {
            qid: q for qid, q in data["quests"].items()
            if q.get("guild_id") != guild_id
        }
        after = len(data["quests"])
        _save(data)
        return before - after
