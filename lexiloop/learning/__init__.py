"""Terminal-based technical English learning for LexiLoop."""

from .service import VocabularyCoach
from .store import LearningStore, default_learning_dir
from .vocabulary import VocabularyEntry, load_vocabulary

__all__ = [
    "LearningStore",
    "VocabularyCoach",
    "VocabularyEntry",
    "default_learning_dir",
    "load_vocabulary",
]
