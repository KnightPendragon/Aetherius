"""
Utilities for parsing quest parameters from Discord forum thread titles,
tags, and original messages.
"""

import re
from typing import Optional

# ── Status / Mode / Type keywords ─────────────────────────────────────────────
VALID_STATUS = {"RECRUITING", "FULL", "COMPLETED", "CANCELLED"}
VALID_MODE   = {"ONLINE", "OFFLINE"}
VALID_TYPE   = {"ONESHOT", "CAMPAIGN"}

# Keywords that hint at the game system inside the message body
SYSTEM_KEYWORDS = [
    r"\bD&D\b", r"\bDND\b", r"\bDungeons\s*&?\s*Dragons\b",
    r"\bPathfinder\b", r"\bPF2e?\b",
    r"\bCall of Cthulhu\b", r"\bCoC\b",
    r"\bVampire\b", r"\bV5\b", r"\bVtM\b",
    r"\bSavage Worlds\b",
    r"\bFate\b",
    r"\bCyberpunk\b",
    r"\bShadowrun\b",
    r"\bStarfinder\b",
    r"\bBlades in the Dark\b",
    r"\bDelta Green\b",
    r"\bWarhammer\b", r"\bWFRP\b",
    r"\b13th Age\b",
    r"\bTraveller\b",
    r"\bMythras\b",
    r"\bDCC\b",
]

BRACKET_RE = re.compile(r"\[([^\]]+)\]")


def parse_title(title: str) -> dict:
    """
    Parse a forum thread title into quest parameters.

    Expected format (order flexible):
        [STATUS] [MODE] [TYPE] [SYSTEM] Quest Title Words
    """
    result = {
        "status":       None,
        "mode":         None,
        "quest_type":   None,
        "system":       None,
        "title":        None,
    }

    bracketed = BRACKET_RE.findall(title)
    remainder = BRACKET_RE.sub("", title).strip()

    for token in bracketed:
        upper = token.strip().upper()
        if upper in VALID_STATUS:
            result["status"] = upper
        elif upper in VALID_MODE:
            result["mode"] = upper
        elif upper in VALID_TYPE:
            result["quest_type"] = upper
        else:
            # Treat as system if nothing else matched it
            if result["system"] is None:
                result["system"] = token.strip().upper()

    result["title"] = remainder if remainder else "Untitled Quest"
    return result


def parse_system_from_body(body: str) -> Optional[str]:
    """Attempt to detect the game system from the quest body text."""
    for pattern in SYSTEM_KEYWORDS:
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            return m.group(0).strip().upper()
    return None


def build_thread_title(quest: dict) -> str:
    """
    Reconstruct the canonical thread title from quest parameters.
    Format: [STATUS] [MODE] [TYPE] [SYSTEM] Quest Title
    """
    parts = []
    if quest.get("status"):
        parts.append(f"[{quest['status']}]")
    if quest.get("mode"):
        parts.append(f"[{quest['mode']}]")
    if quest.get("quest_type"):
        parts.append(f"[{quest['quest_type']}]")
    if quest.get("system"):
        parts.append(f"[{quest['system']}]")
    parts.append(quest.get("title", "Untitled Quest"))
    return " ".join(parts)


def status_colour(status: str) -> int:
    """Return an embed colour integer for a given status."""
    return {
        "RECRUITING": 0x57F287,   # green
        "FULL":       0xFEE75C,   # yellow
        "COMPLETED":  0x5865F2,   # blurple
        "CANCELLED":  0xED4245,   # red
    }.get(status, 0x99AAB5)       # grey default
