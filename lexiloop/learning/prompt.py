"""Prompt-toolkit input UI with a persistent translation panel."""

from __future__ import annotations

import builtins
import sys
from collections.abc import Callable

from .service import TranslationLearningService


class LearningPrompt:
    def __init__(self, service: TranslationLearningService, *, stdin=None, stdout=None, fallback_input=None):
        self.service = service
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.fallback_input: Callable[[str], str] | None = fallback_input
        self._session = None
        self._style = None
        self._rich = False
        if self._is_interactive():
            self._prepare_rich_prompt()
        self.service.add_listener(self.invalidate)

    def _is_interactive(self) -> bool:
        return bool(getattr(self.stdin, "isatty", lambda: False)() and getattr(self.stdout, "isatty", lambda: False)())

    def _prepare_rich_prompt(self) -> None:
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.styles import Style
        except ImportError:
            return
        self._session = PromptSession()
        self._style = Style.from_dict(
            {
                "brand": "bold #79e6b1", "arrow": "bold #d787ff",
                "heading": "bold #ffd75f", "translation": "#87d7ff",
                "word": "bold #eeeeee", "detail": "#b0b0b0",
                "hint": "#808080", "error": "#ff6b6b",
            }
        )
        self._rich = True

    def invalidate(self) -> None:
        if self._session is None:
            return
        try:
            self._session.app.invalidate()
        except Exception:
            pass

    @staticmethod
    def message():
        return [("class:brand", "lexi"), ("class:arrow", " ❯ ")]

    def toolbar(self):
        status = self.service.status
        result = self.service.current
        if status == "translating":
            return [("class:heading", " English learning "), ("class:hint", "Translating the latest prompt in the background...")]
        if status == "error":
            return [("class:heading", " English learning "), ("class:error", self.service.error)]
        if result is None:
            return [("class:heading", " English learning "), ("class:hint", "Send a prompt to generate its English translation.  /stats")]
        fragments = [("class:heading", " English learning "), ("class:translation", result.translation)]
        for detail in result.words[:5]:
            fragments.extend([
                ("", "\n "),
                ("class:word", f"{detail.word:<14}"),
                ("class:detail", f"{detail.part_of_speech:<12} {detail.meaning}"),
            ])
        hidden = max(0, len(result.words) - 5)
        fragments.extend([
            ("", "\n "),
            ("class:hint", f"Showing {min(5, len(result.words))}/{len(result.words)} words" + (f" · {hidden} more stored" if hidden else "") + " · /english · /stats"),
        ])
        return fragments

    def read(self) -> str:
        if self._rich:
            try:
                return self._session.prompt(self.message(), bottom_toolbar=self.toolbar, style=self._style)
            except (EOFError, KeyboardInterrupt):
                raise
            except Exception:
                self._rich = False
        self.stdout.write("\n" + self.service.panel_text() + "\n")
        reader = self.fallback_input or builtins.input
        return reader("lexi > ")
