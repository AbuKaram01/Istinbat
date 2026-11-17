# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The question-answering engine: the single entry point for the interface layer.

    engine = Engine.load(settings, on_progress=...)
    result = engine.ask("question", history, on_stage=..., on_token=..., cancel=...)

Nothing here depends on GTK or on the interface language. The interface calls
``ask`` from a background thread and translates ``AskStatus`` and progress keys.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .generation import Generation, generate_answer
from .history import ChatHistory
from .indexer import IndexReport, index_library, rebuild_library, remove_book
from .language import ContentLanguage, resolve_answer_language
from .models import load_embedder, load_llm, load_reranker, open_collection
from .progress import (
    CancelCheck,
    Progress,
    ProgressCallback,
    ProgressKey,
    Stage,
    StageCallback,
    StageEvent,
    TokenCallback,
)
from .prompts import answer_prompt, refusal_sentences, system_prompt
from .retrieval import Candidate, Retriever, build_context, reciprocal_rank_fusion
from .rewriting import needs_rewrite, rewrite_question
from .safety import CheckedAnswer, PromptGuard, allowed_urls, check_answer, protected_lines
from .settings import Settings


class AskStatus(str, Enum):
    """How an ``ask`` call ended; the interface turns it into a localized message."""

    OK = "ok"
    NO_BOOKS = "no_books"        # Nothing has been indexed yet.
    NO_RESULTS = "no_results"    # The chosen books produced no candidate sources.
    CANCELLED = "cancelled"      # ``answer`` may hold a partial answer.
    BLOCKED = "blocked"          # The answer leaked internal instructions and was withheld.


class _Cancelled(Exception):
    """Raised internally at safe points when cancellation is requested."""


@dataclass(frozen=True)
class Source:
    book: str
    text: str
    score: float


@dataclass
class AskResult:
    question: str                                   # As typed by the user.
    standalone: str                                 # After rewriting; used for searching.
    answer_language: ContentLanguage = ContentLanguage.AR
    answer: str = ""
    status: AskStatus = AskStatus.OK
    sources: list[Source] = field(default_factory=list)
    timings: dict[Stage, float] = field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    first_token_seconds: float | None = None

    @property
    def total_seconds(self) -> float:
        return sum(self.timings.values())

    @property
    def cancelled(self) -> bool:
        return self.status is AskStatus.CANCELLED


class _StageTimer:
    """Measures pipeline stages and reports their start and end."""

    def __init__(self, timings: dict[Stage, float], on_stage: StageCallback | None) -> None:
        self._timings = timings
        self._on_stage = on_stage

    @contextlib.contextmanager
    def stage(self, stage: Stage) -> Iterator[None]:
        if self._on_stage:
            self._on_stage(stage, StageEvent.START, 0.0)
        started = time.perf_counter()
        try:
            yield
        finally:
            self._timings[stage] = time.perf_counter() - started
        if self._on_stage:
            self._on_stage(stage, StageEvent.DONE, self._timings[stage])


class Engine:
    def __init__(self, settings: Settings, retriever: Retriever, llm: Any) -> None:
        self.settings = settings
        self.retriever = retriever
        self.llm = llm

    @classmethod
    def load(cls, settings: Settings, on_progress: ProgressCallback | None = None) -> Engine:
        """Load the vector store and all models, reporting progress for the splash screen."""
        def report(fraction: float, key: ProgressKey) -> None:
            if on_progress:
                on_progress(Progress(fraction, key))

        report(0.05, ProgressKey.LOAD_DATABASE)
        collection = open_collection(settings)
        report(0.15, ProgressKey.LOAD_EMBEDDER)
        embedder = load_embedder(settings)
        report(0.40, ProgressKey.LOAD_RERANKER)
        reranker = load_reranker(settings)

        report(0.55, ProgressKey.LOAD_SEARCH_INDEX)
        retriever = Retriever(collection=collection, embedder=embedder, reranker=reranker)
        retriever.refresh()

        report(0.65, ProgressKey.LOAD_LLM)
        llm = load_llm(settings)

        report(1.0, ProgressKey.LOAD_READY)
        return cls(settings, retriever, llm)

    # -- Library management (reuses the loaded embedder) ----------------------

    def index_library(self, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None) -> IndexReport:
        """Index new and modified books, then refresh the search index."""
        report = index_library(
            self.settings,
            embedder=self.retriever.embedder,
            collection=self.retriever.collection,
            progress=progress,
            cancel=cancel,
        )
        self.retriever.refresh()
        return report

    def rebuild_index(self, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None) -> IndexReport:
        """Wipe the index and rebuild it from scratch, then refresh the search index."""
        report = rebuild_library(
            self.settings,
            embedder=self.retriever.embedder,
            collection=self.retriever.collection,
            progress=progress,
            cancel=cancel,
        )
        self.retriever.refresh()
        return report

    def remove_book(self, path: str) -> bool:
        """Take one book out of the index, then refresh the search index; False if it was not indexed."""
        removed = remove_book(self.settings, path, collection=self.retriever.collection)
        if removed:
            self.retriever.refresh()
        return removed

    def books(self) -> list[str]:
        """Names of the indexed books, for the search-scope picker."""
        return self.retriever.books()

    # -- Question answering ---------------------------------------------------

    def ask(
        self,
        question: str,
        history: ChatHistory | None = None,
        *,
        on_stage: StageCallback | None = None,
        on_token: TokenCallback | None = None,
        cancel: CancelCheck | None = None,
        books: Collection[str] | None = None,
    ) -> AskResult:
        """Answer ``question`` from the indexed books.

        Pipeline: optional rewrite, vector + keyword search, rank fusion,
        reranking, generation.

        Args:
            history: Earlier turns; updated after a complete answer.
            on_stage: Notified when each pipeline stage starts and finishes.
            on_token: When given, the answer is streamed fragment by fragment.
            cancel: Polled at safe points; returning True stops the call.
            books: Restrict the search to these book names (None means all books).
        """
        guard = PromptGuard.new()
        limit = self.settings.retrieval.max_question_chars
        result = AskResult(question=question, standalone=question[:limit])
        timer = _StageTimer(result.timings, on_stage)

        def check_cancelled() -> None:
            if cancel is not None and cancel():
                raise _Cancelled

        try:
            check_cancelled()
            if self.retriever.is_empty:
                result.status = AskStatus.NO_BOOKS
                return result

            result.standalone = self._standalone_question(result.standalone, history, guard, timer)
            check_cancelled()

            top = self._retrieve(result.standalone, books, timer, check_cancelled)
            result.sources = [Source(c.source, c.text, c.score) for c in top]
            if not top:
                result.status = AskStatus.NO_RESULTS
                return result

            result.answer_language = resolve_answer_language(
                self.settings.memory.answer_language, result.standalone,
            )
            context = build_context(top, self.settings.retrieval.max_context_chars, result.answer_language)
            generation = self._generate(
                result.standalone, context, history, result.answer_language, guard, on_token, cancel, timer,
            )
            checked = check_answer(
                generation.text,
                guard,
                protected_lines(system_prompt(result.answer_language, guard), exempt=refusal_sentences()),
                allowed_urls(context, result.standalone),
            )
            self._store_generation(result, generation, checked, history)
        except _Cancelled:
            result.status = AskStatus.CANCELLED

        return result

    def _standalone_question(
        self, question: str, history: ChatHistory | None, guard: PromptGuard, timer: _StageTimer,
    ) -> str:
        if not needs_rewrite(question, history, self.settings.memory):
            return question
        with timer.stage(Stage.REWRITE):
            return rewrite_question(question, history, self.settings.memory, self.llm, guard)

    def _retrieve(
        self,
        question: str,
        books: Collection[str] | None,
        timer: _StageTimer,
        check_cancelled: CancelCheck,
    ) -> list[Candidate]:
        config = self.settings.retrieval
        retriever = self.retriever

        with timer.stage(Stage.VECTOR):
            embedding = retriever.embed_query(question)
            vector_hits = retriever.vector_search(embedding, config.candidates_per_source, books)
        check_cancelled()

        with timer.stage(Stage.BM25):
            keyword_hits = retriever.bm25_search(question, config.candidates_per_source, books)
        check_cancelled()

        fused = reciprocal_rank_fusion([vector_hits, keyword_hits], config.rrf_k)[:config.rerank_pool]
        with timer.stage(Stage.RERANK):
            top = retriever.rerank(question, retriever.to_candidates(fused), config.top_sources)
        check_cancelled()
        return top

    def _generate(
        self,
        question: str,
        context: str,
        history: ChatHistory | None,
        language: ContentLanguage,
        guard: PromptGuard,
        on_token: TokenCallback | None,
        cancel: CancelCheck | None,
        timer: _StageTimer,
    ) -> Generation:
        messages = answer_prompt(question, context, language, guard, history.as_messages() if history else [])
        with timer.stage(Stage.LLM):
            return generate_answer(
                self.llm,
                messages,
                max_tokens=self.settings.llm.max_answer_tokens,
                temperature=self.settings.llm.temperature,
                on_token=on_token,
                cancel=cancel,
            )

    @staticmethod
    def _store_generation(
        result: AskResult, generation: Generation, checked: CheckedAnswer, history: ChatHistory | None,
    ) -> None:
        """Record the checked answer; a blocked answer is dropped and never enters the history."""
        result.prompt_tokens = generation.prompt_tokens
        result.completion_tokens = generation.completion_tokens
        result.first_token_seconds = generation.first_token_seconds
        if checked.blocked:
            result.status = AskStatus.BLOCKED
            return
        result.answer = checked.text
        if generation.cancelled:
            result.status = AskStatus.CANCELLED
        elif history is not None and checked.text:
            history.add(result.standalone, checked.text)
