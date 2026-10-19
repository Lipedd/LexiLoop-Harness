"""SQLite persistence for prompt translations and word occurrences."""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path


def default_learning_dir() -> Path:
    """Return a user-level data directory shared by every code workspace."""

    configured_home = os.environ.get("LEXILOOP_HOME", "").strip()
    base = Path(configured_home).expanduser() if configured_home else Path.home() / ".lexiloop"
    return base / "learning"


class LearningStore:
    """Store every translated word occurrence without storing the source prompt."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else default_learning_dir()
        self.database_path = self.root / "vocabulary.db"
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS translation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    session_id TEXT,
                    word_count INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS word_occurrences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    translation_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    word TEXT NOT NULL,
                    normalized_word TEXT NOT NULL,
                    part_of_speech TEXT NOT NULL,
                    meaning TEXT NOT NULL,
                    FOREIGN KEY (translation_id) REFERENCES translation_runs(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_word_occurrences_normalized
                    ON word_occurrences(normalized_word);
                CREATE INDEX IF NOT EXISTS idx_translation_runs_created
                    ON translation_runs(created_at);
                """
            )

    def record(self, result, *, session_id: str | None = None) -> int:
        """Atomically save one translation and all of its word occurrences."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO translation_runs(created_at, session_id, word_count)
                VALUES (?, ?, ?)
                """,
                (result.created_at, session_id, len(result.words)),
            )
            translation_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO word_occurrences(
                    translation_id, position, word, normalized_word, part_of_speech, meaning
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        translation_id,
                        position,
                        detail.word,
                        detail.normalized,
                        detail.part_of_speech,
                        detail.meaning,
                    )
                    for position, detail in enumerate(result.words)
                ],
            )
        return translation_id

    def statistics(self, *, top_limit: int = 10) -> dict:
        today = date.today().isoformat()
        with self._connect() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) AS translations,
                       COALESCE(SUM(word_count), 0) AS occurrences
                FROM translation_runs
                """
            ).fetchone()
            unique_words = connection.execute(
                "SELECT COUNT(DISTINCT normalized_word) FROM word_occurrences"
            ).fetchone()[0]
            today_totals = connection.execute(
                """
                SELECT COUNT(*) AS translations,
                       COALESCE(SUM(word_count), 0) AS occurrences
                FROM translation_runs
                WHERE substr(created_at, 1, 10) = ?
                """,
                (today,),
            ).fetchone()
            top_words = connection.execute(
                """
                SELECT normalized_word AS word, COUNT(*) AS count,
                       MAX(part_of_speech) AS part_of_speech,
                       MAX(meaning) AS meaning
                FROM word_occurrences
                GROUP BY normalized_word
                ORDER BY count DESC, normalized_word ASC
                LIMIT ?
                """,
                (top_limit,),
            ).fetchall()
        return {
            "translations": int(totals["translations"]),
            "occurrences": int(totals["occurrences"]),
            "unique_words": int(unique_words),
            "today_translations": int(today_totals["translations"]),
            "today_occurrences": int(today_totals["occurrences"]),
            "top_words": [dict(row) for row in top_words],
        }
