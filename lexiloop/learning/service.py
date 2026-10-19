"""Selection, progress, and statistics for the terminal vocabulary coach."""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from .store import LearningStore
from .vocabulary import VocabularyEntry, load_vocabulary


@dataclass
class WordProgress:
    shown: int = 0
    known: int = 0
    again: int = 0
    used: int = 0
    last_shown: str = ""
    last_decision: str = ""


class VocabularyCoach:
    """A small state machine kept deliberately outside the agent runtime."""

    def __init__(
        self,
        entries: tuple[VocabularyEntry, ...] | None = None,
        store: LearningStore | None = None,
        *,
        session_id: str | None = None,
        rng: random.Random | None = None,
    ):
        self.entries = entries or load_vocabulary()
        self.by_word = {entry.word: entry for entry in self.entries}
        self.store = store or LearningStore()
        self.session_id = session_id
        self.rng = rng or random.Random()
        self.events = [
            event for event in self.store.read_events() if event["word"] in self.by_word
        ]
        self.progress = self._build_progress(self.events)
        self._stats_cache = None
        self.current: VocabularyEntry | None = None
        self.notice = ""
        self.next_word()

    @staticmethod
    def _build_progress(events: list[dict]) -> dict[str, WordProgress]:
        result: dict[str, WordProgress] = defaultdict(WordProgress)
        for item in events:
            progress = result[item["word"]]
            event = item["event"]
            if hasattr(progress, event):
                setattr(progress, event, getattr(progress, event) + 1)
            if event == "shown":
                progress.last_shown = str(item.get("timestamp", ""))
            if event in {"known", "again"}:
                progress.last_decision = event
        return dict(result)

    def _record(self, event: str, word: str) -> None:
        item = self.store.append(event, word, session_id=self.session_id)
        self.events.append(item)
        self.progress = self._build_progress(self.events)
        self._stats_cache = None

    def next_word(self) -> VocabularyEntry:
        candidates = [entry for entry in self.entries if entry != self.current]
        unseen = [entry for entry in candidates if self.progress.get(entry.word, WordProgress()).shown == 0]
        needs_review = [
            entry
            for entry in candidates
            if self.progress.get(entry.word, WordProgress()).last_decision == "again"
        ]
        if unseen:
            chosen = self.rng.choice(unseen)
        elif needs_review:
            chosen = min(
                needs_review,
                key=lambda entry: self.progress[entry.word].last_shown,
            )
        else:
            chosen = min(
                candidates or list(self.entries),
                key=lambda entry: self.progress.get(entry.word, WordProgress()).last_shown,
            )
        self.current = chosen
        self._record("shown", chosen.word)
        self.notice = "next word"
        return chosen

    def mark_known(self) -> VocabularyEntry:
        if self.current is not None:
            word = self.current.word
            self._record("known", word)
            selected = self.next_word()
            self.notice = f"mastered: {word}"
            return selected
        return self.next_word()

    def mark_again(self) -> VocabularyEntry:
        if self.current is not None:
            word = self.current.word
            self._record("again", word)
            selected = self.next_word()
            self.notice = f"review later: {word}"
            return selected
        return self.next_word()

    def observe_prompt(self, prompt: str) -> list[str]:
        """Record dictionary words genuinely used, without storing the prompt."""

        tokens = set(re.findall(r"[A-Za-z][A-Za-z-]*", prompt.lower()))
        used = sorted(tokens.intersection(self.by_word))
        for word in used:
            self._record("used", word)
        if used:
            self.notice = "used: " + ", ".join(used[:3])
        return used

    def word_text(self) -> str:
        entry = self.current
        if entry is None:
            return "No vocabulary word is available."
        tags = " · ".join(entry.tags)
        return (
            f"◇ {entry.word}  {entry.phonetic}\n"
            f"  {entry.meaning}"
            + (f"  [{tags}]" if tags else "")
            + f"\n  {entry.example}"
        )

    def statistics(self) -> dict:
        if self._stats_cache is not None:
            return self._stats_cache
        today = date.today().isoformat()
        total_counts = Counter(item["event"] for item in self.events)
        today_counts = Counter(
            item["event"]
            for item in self.events
            if str(item.get("timestamp", "")).startswith(today)
        )
        shown_words = {item["word"] for item in self.events if item["event"] == "shown"}
        used_words = {item["word"] for item in self.events if item["event"] == "used"}
        mastered_words = {
            word for word, progress in self.progress.items() if progress.last_decision == "known"
        }
        review_words = {
            word for word, progress in self.progress.items() if progress.last_decision == "again"
        }
        self._stats_cache = {
            "vocabulary_size": len(self.entries),
            "shown_words": len(shown_words),
            "mastered_words": len(mastered_words),
            "review_words": len(review_words),
            "used_words": len(used_words),
            "total": dict(total_counts),
            "today": dict(today_counts),
        }
        return self._stats_cache

    def stats_text(self) -> str:
        stats = self.statistics()
        today = stats["today"]
        total = stats["total"]
        return (
            "English learning stats\n"
            f"  Today     shown {today.get('shown', 0)} · mastered {today.get('known', 0)} · "
            f"again {today.get('again', 0)} · used {today.get('used', 0)}\n"
            f"  All time  explored {stats['shown_words']}/{stats['vocabulary_size']} · "
            f"mastered {stats['mastered_words']} · review {stats['review_words']} · "
            f"used {stats['used_words']} words ({total.get('used', 0)} times)"
        )
