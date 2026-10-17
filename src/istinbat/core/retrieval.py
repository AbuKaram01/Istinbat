# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Retrieval: semantic (vector) search, keyword (BM25) search, rank fusion and reranking."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from .arabic import preprocess
from .language import ContentLanguage
from .prompts import source_entry
from .tokenizer import tokenize


@dataclass(frozen=True)
class Candidate:
    """A chunk considered as a source for the answer."""

    text: str
    source: str
    normalized_text: str
    score: float = 0.0   # Reranker score; zero until reranked.


@dataclass
class Retriever:
    """Combines the vector store, the BM25 index and the models needed to search.

    ``refresh`` builds new structures before swapping them in, but callers must
    not search and index at the same time; the background worker serializes both.
    """

    collection: Any
    embedder: Any
    reranker: Any
    bm25: Any = None
    chunk_index: dict[int, Candidate] = field(default_factory=dict)
    candidates_by_text: dict[str, Candidate] = field(default_factory=dict)
    chunk_sources: Any = None   # numpy array holding each chunk's book name.

    @property
    def is_empty(self) -> bool:
        return self.bm25 is None

    def refresh(self) -> int:
        """Rebuild the BM25 index and lookup tables from the vector store.

        Returns the number of chunks. Call after every indexing run.
        """
        data = self.collection.get(include=["documents", "metadatas"])
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []

        if not documents:
            self.bm25, self.chunk_index, self.candidates_by_text, self.chunk_sources = None, {}, {}, None
            return 0

        from rank_bm25 import BM25Okapi

        candidates = [
            Candidate(text=text, source=meta["source"], normalized_text=meta["norm_text"])
            for text, meta in zip(documents, metadatas, strict=True)
        ]
        self.bm25 = BM25Okapi([tokenize(c.normalized_text) for c in candidates])
        self.chunk_index = dict(enumerate(candidates))
        self.candidates_by_text = {c.text: c for c in candidates}
        self.chunk_sources = np.array([c.source for c in candidates])
        return len(candidates)

    # -- Search scope ---------------------------------------------------------

    def books(self) -> list[str]:
        """Names of all indexed books, sorted."""
        return [] if self.chunk_sources is None else sorted(set(self.chunk_sources.tolist()))

    def _scope_mask(self, books: Collection[str] | None) -> Any:
        """Return None (no restriction) or a boolean mask of chunks inside ``books``."""
        if books is None or self.chunk_sources is None:
            return None
        return np.isin(self.chunk_sources, list(books))

    # -- Search ---------------------------------------------------------------

    def embed_query(self, text: str) -> list:
        return self.embedder.encode(
            [preprocess(text)], normalize_embeddings=True, show_progress_bar=False,
        ).tolist()

    def vector_search(
        self,
        query_embedding: list,
        limit: int,
        books: Collection[str] | None = None,
    ) -> list[str]:
        """Return the chunk texts nearest to the query, optionally within some books."""
        total = self.collection.count()
        if total == 0:
            return []

        count = min(limit, total)
        filters: dict[str, Any] = {}
        if books is not None:
            mask = self._scope_mask(books)
            in_scope = int(mask.sum()) if mask is not None else 0
            if in_scope == 0:
                return []
            count = min(limit, in_scope)
            filters["where"] = {"source": {"$in": list(books)}}

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=count,
            include=["documents"],
            **filters,
        )
        return results["documents"][0]

    def bm25_search(
        self,
        query: str,
        limit: int,
        books: Collection[str] | None = None,
    ) -> list[str]:
        """Return the chunk texts that best match the query's keywords.

        Chunks with a zero score do not match at all and are never returned.
        """
        if self.bm25 is None:
            return []
        tokens = tokenize(preprocess(query))
        if not tokens:
            return []

        scores = np.asarray(self.bm25.get_scores(tokens))
        mask = self._scope_mask(books)
        if mask is not None:
            scores = np.where(mask, scores, 0.0)

        limit = min(limit, len(scores))
        if limit == 0:
            return []

        # argpartition avoids sorting the whole corpus.
        best = np.argpartition(scores, -limit)[-limit:]
        best = best[np.argsort(scores[best])[::-1]]
        return [self.chunk_index[int(i)].text for i in best if scores[i] > 0 and int(i) in self.chunk_index]

    # -- Reranking ------------------------------------------------------------

    def to_candidates(self, texts: list[str]) -> list[Candidate]:
        """Resolve fused chunk texts to candidates, tolerating texts missing from the index."""
        return [
            self.candidates_by_text.get(text) or Candidate(text, "unknown", preprocess(text))
            for text in texts
        ]

    def rerank(self, question: str, candidates: list[Candidate], top_k: int) -> list[Candidate]:
        """Order candidates by cross-encoder relevance and keep the best ``top_k``."""
        if not candidates:
            return []

        normalized_question = preprocess(question)
        pairs = [[normalized_question, c.normalized_text] for c in candidates]
        scores = np.asarray(self.reranker.predict(pairs))

        best = np.argsort(scores)[::-1][:top_k]
        return [replace(candidates[int(i)], score=float(scores[int(i)])) for i in best]


def reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int) -> list[str]:
    """Merge several ranked lists with reciprocal rank fusion.

    Each item scores ``sum(1 / (k + rank))`` across lists. Only ranks matter,
    so vector and BM25 scores never need to be put on a common scale.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, text in enumerate(ranked):
            scores[text] = scores.get(text, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda text: scores[text], reverse=True)


def build_context(candidates: list[Candidate], max_chars: int, language: ContentLanguage = ContentLanguage.AR) -> str:
    """Join candidates into the prompt context, keeping whole chunks where possible.

    The first chunk that does not fit is cut (with an ellipsis) if enough room
    remains to be useful; everything after it is dropped.
    """
    min_useful_chars = 100
    parts: list[str] = []
    used = 0

    for candidate in candidates:
        entry = source_entry(candidate.source, candidate.text, language)
        if used + len(entry) > max_chars:
            remaining = max_chars - used
            if remaining > min_useful_chars:
                parts.append(entry[:remaining] + "…")
            break
        parts.append(entry)
        used += len(entry)

    return "\n\n".join(parts)
