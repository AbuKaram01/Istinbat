# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tracks which book files are indexed and with which chunking parameters."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from .books import BookFile
from .settings import IndexingConfig

# Bump when the chunking or normalization algorithm changes: every book is then re-indexed.
CHUNKING_VERSION = "v3-bilingual-sentences"


def chunking_signature(config: IndexingConfig) -> str:
    """Fingerprint of everything that influences how a book is chunked."""
    return (
        f"{CHUNKING_VERSION}|{config.max_chunk_chars}|{config.min_chunk_chars}"
        f"|{config.overlap_sentences}|{config.min_sentence_chars}"
    )


def content_digest(content: str, config: IndexingConfig) -> str:
    """Digest of a book's text combined with the chunking signature."""
    payload = f"{chunking_signature(config)}\n{content}"
    return hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()


class Manifest:
    """Persistent mapping of book path to the digest it was indexed with."""

    def __init__(self, path: str, entries: dict[str, str] | None = None) -> None:
        self._path = path
        self._entries: dict[str, str] = dict(entries or {})

    @classmethod
    def load(cls, path: str) -> Manifest:
        """Load a manifest; a missing or corrupt file yields an empty one."""
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return cls(path)
        return cls(path, data if isinstance(data, dict) else None)

    def save(self) -> None:
        """Write the manifest atomically."""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        temporary = self._path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self._entries, handle, indent=2, ensure_ascii=False)
        os.replace(temporary, self._path)

    def digest_of(self, path: str) -> str | None:
        return self._entries.get(path)

    def record(self, path: str, digest: str) -> None:
        self._entries[path] = digest

    def forget(self, path: str) -> None:
        self._entries.pop(path, None)

    def clear(self) -> None:
        self._entries.clear()

    def known_paths(self) -> set[str]:
        return set(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass
class Classification:
    """Books grouped by what indexing must do with them."""

    new: list[BookFile] = field(default_factory=list)
    modified: list[BookFile] = field(default_factory=list)
    unchanged: list[BookFile] = field(default_factory=list)

    @property
    def pending(self) -> list[BookFile]:
        return self.new + self.modified


def classify(files: list[BookFile], manifest: Manifest, config: IndexingConfig) -> Classification:
    """Compare books on disk with the manifest."""
    result = Classification()
    for book in files:
        recorded = manifest.digest_of(book.path)
        if recorded is None:
            result.new.append(book)
        elif recorded != content_digest(book.content, config):
            result.modified.append(book)
        else:
            result.unchanged.append(book)
    return result
