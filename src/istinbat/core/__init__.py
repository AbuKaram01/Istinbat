# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Istinbat engine: retrieval-augmented question answering, independent of any user interface."""

from .engine import AskResult, AskStatus, Engine, Source
from .history import ChatHistory
from .indexer import BookInfo, BookStatus, IndexReport, index_library, rebuild_library, scan_library
from .language import ContentLanguage, detect_language, resolve_answer_language
from .progress import Progress, ProgressKey, Stage, StageEvent
from .settings import (
    AnswerLanguage,
    AppConfig,
    IndexingConfig,
    Language,
    LlmConfig,
    MemoryConfig,
    PathsConfig,
    RetrievalConfig,
    RewriteMode,
    Settings,
    load_settings,
    save_settings,
)

__all__ = [
    "AnswerLanguage", "AppConfig", "AskResult", "AskStatus", "BookInfo", "BookStatus", "ChatHistory",
    "ContentLanguage", "Engine", "IndexReport", "IndexingConfig", "Language", "LlmConfig", "MemoryConfig",
    "PathsConfig", "Progress", "ProgressKey", "RetrievalConfig", "RewriteMode", "Settings", "Source",
    "Stage", "StageEvent", "detect_language", "index_library", "load_settings", "rebuild_library",
    "resolve_answer_language", "save_settings", "scan_library",
]
