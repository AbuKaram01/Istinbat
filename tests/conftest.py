# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test doubles that let the engine run without torch, chromadb or llama.cpp."""

from __future__ import annotations

import os

import numpy as np
import pytest

from istinbat.core import Engine, Settings
from istinbat.core.indexer import index_library
from istinbat.core.retrieval import Retriever


class FakeCollection:
    """Minimal in-memory stand-in for a ChromaDB collection."""

    def __init__(self):
        self.rows: dict[str, tuple[str, dict]] = {}

    def upsert(self, ids, embeddings, documents, metadatas):
        for row_id, document, metadata in zip(ids, documents, metadatas, strict=True):
            self.rows[row_id] = (document, metadata)

    def delete(self, where=None, ids=None):
        if ids is not None:
            for row_id in ids:
                self.rows.pop(row_id, None)
        if where is not None:
            source = where["source"]
            self.rows = {i: r for i, r in self.rows.items() if r[1]["source"] != source}

    def count(self):
        return len(self.rows)

    def get(self, include=None):
        return {
            "ids": list(self.rows),
            "documents": [document for document, _ in self.rows.values()],
            "metadatas": [metadata for _, metadata in self.rows.values()],
        }

    def query(self, query_embeddings, n_results, include, where=None):
        rows = list(self.rows.values())
        if where:
            allowed = where["source"]["$in"]
            rows = [row for row in rows if row[1]["source"] in allowed]
        return {"documents": [[document for document, _ in rows][:n_results]]}


class FakeEmbedder:
    def __init__(self):
        self.calls: list[int] = []

    def encode(self, texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False):
        self.calls.append(len(texts))
        return np.ones((len(texts), 4))


class FakeReranker:
    def predict(self, pairs):
        return np.array([len(pair[1]) for pair in pairs], dtype=float)   # Longer text ranks higher.


class FakeLLM:
    """Answers with fixed text; a rewrite prompt is recognized by having no system message."""

    def __init__(self, answer="a test answer", rewrite="standalone question"):
        self.answer, self.rewrite = answer, rewrite
        self.calls: list[dict] = []

    def create_chat_completion(self, messages, max_tokens, temperature, stream=False):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "stream": stream})
        text = self.rewrite if messages[0]["role"] == "user" else self.answer
        if stream:
            return iter(
                [{"choices": [{"delta": {"role": "assistant"}}]}]
                + [{"choices": [{"delta": {"content": word + " "}}]} for word in text.split()]
            )
        return {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }


class ScriptedLLM(FakeLLM):
    """Like FakeLLM, but the answer is computed from the messages (to simulate a manipulated model)."""

    def __init__(self, respond):
        super().__init__()
        self.respond = respond

    def create_chat_completion(self, messages, max_tokens, temperature, stream=False):
        if messages[0]["role"] == "user":                       # Rewrite prompt: behave normally.
            return super().create_chat_completion(messages, max_tokens, temperature, stream)
        self.answer = self.respond(messages)
        return super().create_chat_completion(messages, max_tokens, temperature, stream)


class OneShotLLM:
    """Returns the same text for every non-streaming call."""

    def __init__(self, text):
        self.text = text

    def create_chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": self.text}}]}


BOOK_A = " ".join(f"الحاسوب جهاز إلكتروني يعالج البيانات رقم {i} بسرعة كبيرة." for i in range(40))
BOOK_B = " ".join(f"المعلومات هي نتائج معالجة البيانات رقم {i} داخل النظام." for i in range(40))


@pytest.fixture
def settings(tmp_path):
    books_dir = tmp_path / "books"
    books_dir.mkdir()
    config = Settings()
    config.paths.books_dir = str(books_dir)
    config.paths.manifest_file = str(tmp_path / "manifest.json")
    config.paths.vector_db = str(tmp_path / "db")
    config.paths.conversations_db = str(tmp_path / "conversations.db")
    return config


@pytest.fixture
def write_book(settings):
    def _write(name: str, text: str) -> str:
        # The same way the library scan builds paths: they are the manifest's keys, and on Windows
        # os.path.join gives backslashes, so a hand-made "dir/name.txt" would never match.
        path = os.path.join(settings.paths.books_dir, f"{name}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path
    return _write


@pytest.fixture
def indexed_engine(settings, write_book):
    """An Engine over a genuinely indexed library (real indexing code, fake libraries)."""
    write_book("computer-book", BOOK_A)
    write_book("information-book", BOOK_B)

    collection, embedder = FakeCollection(), FakeEmbedder()
    index_library(settings, embedder=embedder, collection=collection)

    retriever = Retriever(collection=collection, embedder=embedder, reranker=FakeReranker())
    retriever.refresh()
    return Engine(settings, retriever, FakeLLM())
