"""Prompt-toolkit input UI with a built-in plain-input fallback."""

from __future__ import annotations

import builtins
import sys
from collections.abc import Callable

from .service import VocabularyCoach


class LearningPrompt:
    def __init__(
        self,
        coach: VocabularyCoach,
        *,
        stdin=None,
        stdout=None,
        fallback_input: Callable[[str], str] | None = None,
    ):
        self.coach = coach
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.fallback_input = fallback_input
        self._session = None
        self._style = None
        self._bindings = None
        self._rich = False
        if self._is_interactive():
            self._prepare_rich_prompt()

    def _is_interactive(self) -> bool:
        return bool(
            getattr(self.stdin, "isatty", lambda: False)()
            and getattr(self.stdout, "isatty", lambda: False)()
        )

    def _prepare_rich_prompt(self) -> None:
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.styles import Style
        except ImportError:
            return

        bindings = KeyBindings()

        @bindings.add("escape", "k", eager=True)
        def mark_known(event):
            self._safe_action(self.coach.mark_known)
            event.app.invalidate()

        @bindings.add("escape", "a", eager=True)
        def mark_again(event):
            self._safe_action(self.coach.mark_again)
            event.app.invalidate()

        @bindings.add("escape", "j", eager=True)
        def next_word(event):
            self._safe_action(self.coach.next_word)
            event.app.invalidate()

        self._session = PromptSession()
        self._bindings = bindings
        self._style = Style.from_dict(
            {
                "brand": "bold #79e6b1",
                "arrow": "bold #d787ff",
                "word": "bold #ffd75f",
                "phonetic": "#87d7ff",
                "meaning": "#eeeeee",
                "example": "italic #9e9e9e",
                "hint": "#808080",
                "notice": "#79e6b1",
            }
        )
        self._rich = True

    def _safe_action(self, action) -> None:
        try:
            action()
        except Exception:
            self.coach.notice = "learning storage unavailable"

    @staticmethod
    def message():
        return [("class:brand", "lexi"), ("class:arrow", " ❯ ")]

    def toolbar(self):
        entry = self.coach.current
        if entry is None:
            return [("class:hint", " vocabulary unavailable ")]
        today = self.coach.statistics()["today"]
        notice = f"  {self.coach.notice}" if self.coach.notice else ""
        return [
            ("class:word", f" ◇ {entry.word} "),
            ("class:phonetic", f"{entry.phonetic}  "),
            ("class:meaning", entry.meaning),
            ("", "\n "),
            ("class:example", entry.example),
            ("", "\n "),
            (
                "class:hint",
                f"Today {today.get('shown', 0)} shown · {today.get('known', 0)} mastered · "
                f"{today.get('used', 0)} used  |  Alt+K mastered · Alt+A again · Alt+J next · /stats",
            ),
            ("class:notice", notice),
        ]

    def read(self) -> str:
        if self._rich:
            try:
                return self._session.prompt(
                    self.message(),
                    bottom_toolbar=self.toolbar,
                    key_bindings=self._bindings,
                    style=self._style,
                )
            except (EOFError, KeyboardInterrupt):
                raise
            except Exception:
                # Terminal capability problems must not take the coding agent down.
                self._rich = False
        self.stdout.write("\n" + self.coach.word_text() + "\n")
        reader = self.fallback_input or builtins.input
        return reader("lexi > ")
