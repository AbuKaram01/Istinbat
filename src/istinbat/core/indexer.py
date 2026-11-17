# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Incremental indexing of books into the vector store.

Each book is committed (vector store and manifest) as soon as it is finished,
so cancelling or crashing never loses completed work.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from .books import BookFile, book_name, load_book_files
from .chunking import Chunk, build_chunks
from .manifest import Classification, Manifest, classify, content_digest
from .models import load_embedder, open_collection
from .progress import CancelCheck, Progress, ProgressCallback, ProgressKey
from .settings import Settings

_LOAD_EMBEDDER_FRACTION = 0.04
_ENCODE_START_FRACTION = 0.05
_CHUNKING_FRACTION = 0.02
_WIPE_BATCH_SIZE = 1000


class BookStatus(str, Enum):
    NEW = "new"
    MODIFIED = "modified"
    INDEXED = "indexed"


@dataclass(frozen=True)
class BookInfo:
    name: str
    path: str
    status: BookStatus
    characters: int


@dataclass
class IndexReport:
    new_books: int = 0
    modified_books: int = 0
    unchanged_books: int = 0
    removed_books: int = 0
    chunks_added: int = 0
    cancelled: bool = False

    @property
    def nothing_to_do(self) -> bool:
        return not (self.new_books or self.modified_books or self.removed_books)


# -- Vector store operations --------------------------------------------------

def encode_chunks(
    embedder: Any,
    chunks: list[Chunk],
    batch_size: int,
    on_batch: Callable[[int], None] | None = None,
    cancel: CancelCheck | None = None,
) -> np.ndarray | None:
    """Embed chunk texts in batches; returns None if cancelled between batches.

    ``on_batch`` receives the number of chunks encoded so far.
    """
    texts = [chunk.normalized_text for chunk in chunks]
    parts: list[np.ndarray] = []

    for start in range(0, len(texts), batch_size):
        if cancel is not None and cancel():
            return None
        batch = texts[start:start + batch_size]
        parts.append(np.asarray(embedder.encode(
            batch, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False,
        )))
        if on_batch is not None:
            on_batch(min(start + batch_size, len(texts)))

    return np.vstack(parts) if parts else np.zeros((0, 0))


def upsert_chunks(collection: Any, chunks: list[Chunk], embeddings: np.ndarray, batch_size: int) -> None:
    """Store chunks and their embeddings in batches.

    The normalized text is kept in metadata so the BM25 index can be rebuilt from the store.
    """
    for start in range(0, len(chunks), batch_size):
        end = min(start + batch_size, len(chunks))
        batch = chunks[start:end]
        collection.upsert(
            ids=[chunk.id for chunk in batch],
            embeddings=embeddings[start:end].tolist(),
            documents=[chunk.text for chunk in batch],
            metadatas=[{"source": chunk.source, "norm_text": chunk.normalized_text} for chunk in batch],
        )


def delete_book_chunks(collection: Any, book_name: str) -> None:
    collection.delete(where={"source": book_name})


def wipe_collection(collection: Any, batch_size: int = _WIPE_BATCH_SIZE) -> int:
    """Delete every chunk in the collection; returns how many were removed."""
    ids = list(collection.get(include=[]).get("ids", []))
    for start in range(0, len(ids), batch_size):
        collection.delete(ids=ids[start:start + batch_size])
    return len(ids)


# -- Library inspection -------------------------------------------------------

def scan_library(settings: Settings) -> list[BookInfo]:
    """Report the status of every book on disk without changing anything."""
    _require_books_dir(settings)
    manifest = Manifest.load(settings.paths.manifest_file)
    classification = classify(load_book_files(settings.paths.books_dir), manifest, settings.indexing)

    groups = (
        (BookStatus.NEW, classification.new),
        (BookStatus.MODIFIED, classification.modified),
        (BookStatus.INDEXED, classification.unchanged),
    )
    books = [
        BookInfo(book.name, book.path, status, len(book.content))
        for status, members in groups
        for book in members
    ]
    return sorted(books, key=lambda info: info.name)


def indexed_book_names(settings: Settings) -> list[str]:
    """Return the sorted names of the books the index holds, read from the manifest.

    It needs neither the vector store nor a model, so the interface can offer the search scope before the
    engine is loaded.
    """
    manifest = Manifest.load(settings.paths.manifest_file)
    return sorted({book_name(path) for path in manifest.known_paths()})


def _require_books_dir(settings: Settings) -> None:
    if not os.path.isdir(settings.paths.books_dir):
        raise FileNotFoundError(f"Books folder not found: {settings.paths.books_dir}")


# -- Indexing run -------------------------------------------------------------

class _LibraryIndexer:
    """One indexing run over the books folder."""

    def __init__(
        self,
        settings: Settings,
        collection: Any | None,
        embedder: Any | None,
        progress: ProgressCallback | None,
        cancel: CancelCheck | None,
    ) -> None:
        self._settings = settings
        self._collection = collection
        self._embedder = embedder
        self._progress = progress
        self._cancel = cancel
        self._manifest = Manifest.load(settings.paths.manifest_file)
        self._report = IndexReport()

    def run(self) -> IndexReport:
        _require_books_dir(self._settings)
        if self._collection is None:
            self._collection = open_collection(self._settings)

        self._emit(0.0, ProgressKey.INDEX_SCANNING)
        files = load_book_files(self._settings.paths.books_dir)
        self._remove_deleted_books(files)

        classification = classify(files, self._manifest, self._settings.indexing)
        self._count(classification)
        if not classification.pending:
            self._emit(1.0, ProgressKey.INDEX_UP_TO_DATE)
            return self._report

        self._emit(_CHUNKING_FRACTION, ProgressKey.INDEX_CHUNKING)
        indexing = self._settings.indexing
        plan = [(book, build_chunks(book.content, book.path, indexing)) for book in classification.pending]
        total_chunks = sum(len(chunks) for _, chunks in plan)
        if total_chunks and self._embedder is None:
            self._emit(_LOAD_EMBEDDER_FRACTION, ProgressKey.INDEX_LOADING_EMBEDDER)
            self._embedder = load_embedder(self._settings)

        replaced = {book.path for book in classification.modified}
        self._index_books(plan, total_chunks, replaced)

        if not self._report.cancelled:
            self._emit(1.0, ProgressKey.INDEX_DONE)
        return self._report

    def _remove_deleted_books(self, files: list[BookFile]) -> None:
        on_disk = {book.path for book in files}
        removed = self._manifest.known_paths() - on_disk
        for path in removed:
            delete_book_chunks(self._collection, book_name(path))
            self._manifest.forget(path)
        self._report.removed_books = len(removed)
        if removed:
            self._manifest.save()

    def _count(self, classification: Classification) -> None:
        self._report.new_books = len(classification.new)
        self._report.modified_books = len(classification.modified)
        self._report.unchanged_books = len(classification.unchanged)

    def _index_books(self, plan: list[tuple[BookFile, list[Chunk]]], total_chunks: int, replaced: set[str]) -> None:
        done = 0
        for book, chunks in plan:
            if self._is_cancelled():
                self._report.cancelled = True
                return
            if not self._index_book(book, chunks, book.path in replaced, done, total_chunks):
                self._report.cancelled = True
                return
            done += len(chunks)

    def _index_book(self, book: BookFile, chunks: list[Chunk], replace: bool, done: int, total: int) -> bool:
        """Index one book; returns False if cancelled before it completed."""
        if replace:
            delete_book_chunks(self._collection, book.name)

        if chunks:
            def on_batch(encoded: int) -> None:
                fraction = _ENCODE_START_FRACTION + (1 - _ENCODE_START_FRACTION) * (done + encoded) / total
                self._emit(fraction, ProgressKey.INDEX_ENCODING, book=book.name, done=done + encoded, total=total)

            embeddings = encode_chunks(
                self._embedder, chunks, self._settings.indexing.encode_batch_size, on_batch, self._cancel,
            )
            if embeddings is None:
                return False
            upsert_chunks(self._collection, chunks, embeddings, self._settings.indexing.upsert_batch_size)
            self._report.chunks_added += len(chunks)

        self._manifest.record(book.path, content_digest(book.content, self._settings.indexing))
        self._manifest.save()
        return True

    def _is_cancelled(self) -> bool:
        return self._cancel is not None and self._cancel()

    def _emit(self, fraction: float, key: ProgressKey, **args: object) -> None:
        if self._progress is not None:
            self._progress(Progress(fraction, key, args))


def index_library(
    settings: Settings,
    *,
    embedder: Any | None = None,
    collection: Any | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> IndexReport:
    """Index new and modified books and drop removed ones.

    Pass the engine's already-loaded ``embedder`` and ``collection`` to avoid
    loading them twice. ``cancel`` is polled between embedding batches.
    """
    return _LibraryIndexer(settings, collection, embedder, progress, cancel).run()


def rebuild_library(
    settings: Settings,
    *,
    embedder: Any | None = None,
    collection: Any | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> IndexReport:
    """Wipe the index and manifest, then index every book from scratch.

    If cancelled midway, finished books stay indexed and the rest show as new.
    """
    if collection is None:
        collection = open_collection(settings)
    if progress is not None:
        progress(Progress(0.0, ProgressKey.INDEX_WIPING))

    wipe_collection(collection)
    Manifest(settings.paths.manifest_file).save()

    return index_library(settings, embedder=embedder, collection=collection, progress=progress, cancel=cancel)
