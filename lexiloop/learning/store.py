"""Append-only persistence for English-learning events."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

EVENT_NAMES = frozenset({"shown", "known", "again", "used"})


def default_learning_dir() -> Path:
    """Return a user-level data directory shared by every code workspace."""

    configured_home = os.environ.get("LEXILOOP_HOME", "").strip()
    base = Path(configured_home).expanduser() if configured_home else Path.home() / ".lexiloop"
    return base / "learning"


class LearningStore:
    """Store privacy-minimal events; full user prompts are never persisted here."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else default_learning_dir()
        self.events_path = self.root / "events.jsonl"

    def append(self, event: str, word: str, *, session_id: str | None = None) -> dict:
        if event not in EVENT_NAMES:
            raise ValueError(f"unknown learning event: {event}")
        payload = {
            "version": 1,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            "word": word.lower(),
        }
        if session_id:
            payload["session_id"] = session_id
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return payload

    def read_events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        events = []
        with self.events_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # One damaged line should not make the whole learning layer unusable.
                    continue
                if value.get("event") in EVENT_NAMES and isinstance(value.get("word"), str):
                    events.append(value)
        return events
