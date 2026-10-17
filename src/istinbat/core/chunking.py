# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Split book text into overlapping, sentence-aligned chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .arabic import normalize_arabic
from .books import book_name
from .sentences import split_sentences
from .settings import IndexingConfig

_WHITESPACE = re.compile(r"\s+")
_ID_HASH_LENGTH = 8


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str               # Original text, shown to the user.
    normalized_text: str    # Normalized text, used for search and embeddings.
    source: str             # Book name.


def make_chunk_id(book: str, index: int, text: str) -> str:
    """Build a deterministic id so re-indexing the same text upserts instead of duplicating."""
    digest = hashlib.md5(text.encode()).hexdigest()[:_ID_HASH_LENGTH]
    return f"{book}_c{index}_{digest}"


def group_sentences(sentences: list[str], config: IndexingConfig) -> list[list[int]]:
    """Group consecutive sentence indices into chunks by size, without any model.

    A chunk closes once adding the next sentence would exceed ``max_chunk_chars``
    (and the chunk already holds ``min_chunk_chars``). The last
    ``overlap_sentences`` sentences are repeated at the start of the next chunk
    to preserve context across boundaries.
    """
    groups: list[list[int]] = []
    current = [0]
    current_chars = len(sentences[0])

    for index in range(1, len(sentences)):
        length = len(sentences[index])
        overflows = current_chars + length > config.max_chunk_chars
        if overflows and current_chars >= config.min_chunk_chars:
            groups.append(current)
            overlap = current[-config.overlap_sentences:] if config.overlap_sentences > 0 else []
            current = overlap + [index]
            current_chars = sum(len(sentences[i]) for i in current)
        else:
            current.append(index)
            current_chars += length

    groups.append(current)
    return groups


def build_chunks(text: str, source_path: str, config: IndexingConfig) -> list[Chunk]:
    """Convert a whole book into chunks; returns an empty list if it has no usable sentences."""
    sentences = split_sentences(_WHITESPACE.sub(" ", text).strip(), config.min_sentence_chars)
    if not sentences:
        return []

    normalized = [normalize_arabic(sentence) for sentence in sentences]
    name = book_name(source_path)

    chunks: list[Chunk] = []
    for index, group in enumerate(group_sentences(sentences, config)):
        original_text = " ".join(sentences[i] for i in group)
        chunks.append(Chunk(
            id=make_chunk_id(name, index, original_text),
            text=original_text,
            normalized_text=" ".join(normalized[i] for i in group),
            source=name,
        ))
    return chunks
