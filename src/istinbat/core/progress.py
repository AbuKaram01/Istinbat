# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Progress reporting types.

The core never produces user-facing text. It emits stable keys that the
interface layer translates, so the engine stays independent of the UI language.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum


class ProgressKey(str, Enum):
    """Identifies what a long-running operation is currently doing."""

    LOAD_DATABASE = "load.database"
    LOAD_EMBEDDER = "load.embedder"
    LOAD_RERANKER = "load.reranker"
    LOAD_SEARCH_INDEX = "load.search_index"
    LOAD_LLM = "load.llm"
    LOAD_READY = "load.ready"

    INDEX_SCANNING = "index.scanning"
    INDEX_WIPING = "index.wiping"
    INDEX_CHUNKING = "index.chunking"
    INDEX_LOADING_EMBEDDER = "index.loading_embedder"
    INDEX_ENCODING = "index.encoding"      # args: book, done, total
    INDEX_UP_TO_DATE = "index.up_to_date"
    INDEX_DONE = "index.done"


@dataclass(frozen=True)
class Progress:
    """A progress update: how far along (0..1) and what is happening."""

    fraction: float
    key: ProgressKey
    args: Mapping[str, object] = field(default_factory=dict)


class Stage(str, Enum):
    """Steps of answering a question, in execution order."""

    REWRITE = "rewrite"
    VECTOR = "vector"
    BM25 = "bm25"
    RERANK = "rerank"
    LLM = "llm"


class StageEvent(str, Enum):
    START = "start"
    DONE = "done"


ProgressCallback = Callable[[Progress], None]
StageCallback = Callable[[Stage, StageEvent, float], None]
TokenCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]
