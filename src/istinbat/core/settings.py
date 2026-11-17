# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Application settings: typed sections, JSON persistence and defensive loading."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any

from .paths import data_dir, default_models_dir, default_settings_path, documents_dir


class Language(str, Enum):
    """Interface languages."""

    EN = "en"
    AR = "ar"

    @property
    def is_rtl(self) -> bool:
        return self is Language.AR


class RewriteMode(str, Enum):
    """When follow-up questions are rewritten into standalone questions."""

    ALWAYS = "always"
    AUTO = "auto"   # Only short questions; unreliable for short standalone questions.
    OFF = "off"


class AnswerLanguage(str, Enum):
    """Which language answers are written in."""

    AUTO = "auto"       # The language of the question.
    ARABIC = "ar"
    ENGLISH = "en"


def _default_thread_count() -> int:
    """Use half of the logical CPUs, which matches the physical core count when SMT is on."""
    return max(1, (os.cpu_count() or 2) // 2)


@dataclass
class PathsConfig:
    books_dir: str = field(default_factory=lambda: str(documents_dir() / "Books"))
    embedder_model: str = ""
    reranker_model: str = ""
    llm_model: str = ""
    models_dir: str = field(default_factory=lambda: str(default_models_dir()))   # Where downloads are stored.
    vector_db: str = field(default_factory=lambda: str(data_dir() / "chroma_db"))
    manifest_file: str = field(default_factory=lambda: str(data_dir() / "index_manifest.json"))
    conversations_db: str = field(default_factory=lambda: str(data_dir() / "conversations.db"))
    collection_name: str = "books_collection"

    def models_ready(self) -> bool:
        """Return whether the three models are chosen and present on disk."""
        chosen = (self.embedder_model, self.reranker_model, self.llm_model)
        return all(path and os.path.exists(path) for path in chosen)


@dataclass
class IndexingConfig:
    encode_batch_size: int = 32
    upsert_batch_size: int = 500
    min_sentence_chars: int = 10
    max_chunk_chars: int = 1200
    min_chunk_chars: int = 200
    overlap_sentences: int = 2


@dataclass
class RetrievalConfig:
    candidates_per_source: int = 15   # Results taken from each of vector and keyword search.
    rerank_pool: int = 6              # Fused candidates passed to the reranker.
    top_sources: int = 3              # Sources kept after reranking.
    rrf_k: int = 60                   # Reciprocal rank fusion damping constant.
    max_context_chars: int = 3000
    max_question_chars: int = 4000   # Longer questions are cut: they could overflow the context window.


@dataclass
class LlmConfig:
    context_window: int = 8192
    max_answer_tokens: int = 1024
    temperature: float = 0.1
    gpu_layers: int = 0
    threads: int = field(default_factory=_default_thread_count)
    batch_threads: int = field(default_factory=_default_thread_count)


@dataclass
class MemoryConfig:
    history_turns: int = 3
    history_answer_chars: int = 500
    rewrite_mode: RewriteMode = RewriteMode.ALWAYS
    rewrite_short_words: int = 5
    rewrite_max_tokens: int = 100
    rewrite_max_chars: int = 300
    answer_language: AnswerLanguage = AnswerLanguage.AUTO


@dataclass
class AppConfig:
    language: Language = Language.EN
    notify_on_answer: bool = True
    auto_delete_days: int = 0   # Delete conversations idle for this many days; 0 disables.
    welcome_done: bool = False  # The first-run welcome guide has been shown (or was not needed).


@dataclass
class Settings:
    paths: PathsConfig = field(default_factory=PathsConfig)
    indexing: IndexingConfig = field(default_factory=IndexingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    app: AppConfig = field(default_factory=AppConfig)


def _coerce(current: object, value: object) -> object | None:
    """Return ``value`` converted to the type of ``current``, or None if it does not fit."""
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(current, Enum):
        try:
            return type(current)(value)
        except ValueError:
            return None
    if isinstance(current, bool):
        return value if isinstance(value, bool) else None
    if isinstance(current, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if isinstance(current, float):
        return float(value) if is_number else None
    if isinstance(current, str):
        return value if isinstance(value, str) else None
    return None


def _apply_section(section: object, raw: object) -> None:
    """Copy valid values from the raw JSON mapping onto a settings section."""
    if not isinstance(raw, dict):
        return
    for item in fields(section):  # type: ignore[arg-type]
        if item.name not in raw:
            continue
        coerced = _coerce(getattr(section, item.name), raw[item.name])
        if coerced is not None:
            setattr(section, item.name, coerced)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings over the defaults.

    Unknown keys, values of the wrong type and unreadable files are ignored,
    so a damaged settings file can never prevent the application from starting.
    """
    settings = Settings()
    raw = _read_json_object(Path(path) if path else default_settings_path())
    for section in fields(settings):
        _apply_section(getattr(settings, section.name), raw.get(section.name))
    return settings


def _encode_enum(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def save_settings(settings: Settings, path: str | Path | None = None) -> Path:
    """Write settings atomically (temporary file, then replace)."""
    target = Path(path) if path else default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False, default=_encode_enum),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target
