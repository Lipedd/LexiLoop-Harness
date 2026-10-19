"""Prompt-driven English learning for LexiLoop."""

from .service import TranslationLearningService, TranslationResult, WordDetail
from .store import LearningStore, default_learning_dir

__all__ = [
    "LearningStore",
    "TranslationLearningService",
    "TranslationResult",
    "WordDetail",
    "default_learning_dir",
]
