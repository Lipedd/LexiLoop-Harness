import io
import json
import random

from lexiloop.cli import (
    _configure_stdio_fallback,
    _handle_learning_command,
    _learning_enabled,
    build_arg_parser,
)
from lexiloop.learning.prompt import LearningPrompt
from lexiloop.learning.service import VocabularyCoach
from lexiloop.learning.store import LearningStore, default_learning_dir
from lexiloop.learning.vocabulary import load_vocabulary


class _NonTty(io.StringIO):
    def isatty(self):
        return False


class _ReconfigurableStream:
    def __init__(self):
        self.errors = "strict"

    def reconfigure(self, *, errors):
        self.errors = errors


def test_packaged_vocabulary_has_one_hundred_unique_entries():
    entries = load_vocabulary()

    assert len(entries) == 100
    assert len({entry.word for entry in entries}) == 100
    assert all(entry.meaning and entry.example and entry.tags for entry in entries)


def test_learning_store_skips_a_damaged_event_line(tmp_path):
    store = LearningStore(tmp_path)
    store.append("shown", "schema", session_id="session-1")
    with store.events_path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
    store.append("known", "schema", session_id="session-1")

    events = store.read_events()

    assert [event["event"] for event in events] == ["shown", "known"]


def test_coach_records_progress_without_persisting_the_prompt(tmp_path):
    store = LearningStore(tmp_path)
    coach = VocabularyCoach(
        entries=load_vocabulary(),
        store=store,
        session_id="session-1",
        rng=random.Random(7),
    )
    first_word = coach.current.word

    coach.mark_known()
    used = coach.observe_prompt("Please validate the schema, but never save this sentence.")

    persisted = store.events_path.read_text(encoding="utf-8")
    assert coach.progress[first_word].last_decision == "known"
    assert used == ["schema", "validate"]
    assert "never save this sentence" not in persisted
    assert all("prompt" not in json.loads(line) for line in persisted.splitlines())


def test_coach_statistics_distinguish_shown_mastered_again_and_used(tmp_path):
    coach = VocabularyCoach(store=LearningStore(tmp_path), rng=random.Random(1))
    mastered = coach.current.word
    coach.mark_known()
    review = coach.current.word
    coach.mark_again()
    coach.observe_prompt("validate the schema")

    stats = coach.statistics()

    assert coach.progress[mastered].last_decision == "known"
    assert coach.progress[review].last_decision == "again"
    assert stats["mastered_words"] == 1
    assert stats["review_words"] == 1
    assert stats["used_words"] == 2
    assert stats["today"]["shown"] == 3


def test_learning_commands_work_without_calling_the_agent(tmp_path):
    coach = VocabularyCoach(store=LearningStore(tmp_path), rng=random.Random(2))

    handled, word_output = _handle_learning_command("/word", coach)
    handled_stats, stats_output = _handle_learning_command("/stats", coach)
    handled_bad, bad_output = _handle_learning_command("/word unknown", coach)

    assert handled is True
    assert coach.current.word in word_output
    assert handled_stats is True
    assert "English learning stats" in stats_output
    assert handled_bad is True
    assert bad_output == "Usage: /word [next|known|again]"


def test_plain_input_fallback_keeps_learning_available(tmp_path):
    coach = VocabularyCoach(store=LearningStore(tmp_path), rng=random.Random(3))
    output = _NonTty()
    prompt = LearningPrompt(
        coach,
        stdin=_NonTty(),
        stdout=output,
        fallback_input=lambda label: "hello",
    )

    assert prompt.read() == "hello"
    assert coach.current.word in output.getvalue()
    assert coach.current.meaning in output.getvalue()


def test_toolbar_contains_word_progress_and_keyboard_hints(tmp_path):
    coach = VocabularyCoach(store=LearningStore(tmp_path), rng=random.Random(4))
    prompt = LearningPrompt(coach, stdin=_NonTty(), stdout=_NonTty())

    toolbar = "".join(text for _style, text in prompt.toolbar())

    assert coach.current.word in toolbar
    assert "Today 1 shown" in toolbar
    assert "Alt+K mastered" in toolbar
    assert "/stats" in toolbar


def test_learning_directory_is_global_and_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("LEXILOOP_HOME", str(tmp_path))

    assert default_learning_dir() == tmp_path / "learning"


def test_learning_can_be_disabled_by_flag_or_environment(monkeypatch):
    parser = build_arg_parser()
    monkeypatch.setenv("LEXILOOP_LEARNING", "0")

    assert _learning_enabled(parser.parse_args([])) is False
    monkeypatch.setenv("LEXILOOP_LEARNING", "1")
    assert _learning_enabled(parser.parse_args(["--no-learning"])) is False
    assert _learning_enabled(parser.parse_args([])) is True


def test_stdio_uses_replacement_instead_of_crashing_on_legacy_encoding(monkeypatch):
    stdout = _ReconfigurableStream()
    stderr = _ReconfigurableStream()
    monkeypatch.setattr("lexiloop.cli.sys.stdout", stdout)
    monkeypatch.setattr("lexiloop.cli.sys.stderr", stderr)

    _configure_stdio_fallback()

    assert stdout.errors == "replace"
    assert stderr.errors == "replace"
