"""Load the small, built-in technical-English vocabulary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class VocabularyEntry:
    word: str
    phonetic: str
    meaning: str
    example: str
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict) -> "VocabularyEntry":
        return cls(
            word=str(value["word"]).strip().lower(),
            phonetic=str(value.get("phonetic", "")).strip(),
            meaning=str(value["meaning"]).strip(),
            example=str(value["example"]).strip(),
            tags=tuple(str(tag).strip() for tag in value.get("tags", []) if str(tag).strip()),
        )


def load_vocabulary() -> tuple[VocabularyEntry, ...]:
    """Load and validate the packaged word list.

    Keeping this deterministic and local means the input bar never has to wait
    for an LLM or a network request before it can show a word.
    """

    resource = files("lexiloop.data").joinpath("coding_words.json")
    raw = json.loads(resource.read_text(encoding="utf-8"))
    entries = tuple(VocabularyEntry.from_dict(item) for item in raw)
    words = [entry.word for entry in entries]
    if not entries:
        raise ValueError("the vocabulary is empty")
    if len(words) != len(set(words)):
        raise ValueError("the vocabulary contains duplicate words")
    return entries
