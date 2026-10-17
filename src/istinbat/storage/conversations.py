# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Conversation storage backed by SQLite (standard library only).

A conversation has a title, an optional search scope (a list of book names, or
None for all books) and turns. A turn holds the question, its standalone
rewrite, the answer and the sources. An empty title means "untitled"; the
interface shows a localized placeholder, so no display text is stored.

All operations take a lock, so the store is safe to share between the
interface thread and the background worker.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from ..core.history import ChatHistory, truncate

TITLE_MAX_CHARS = 40
SECONDS_PER_DAY = 86_400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    scope      TEXT,
    created_at REAL    NOT NULL,
    updated_at REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    question        TEXT    NOT NULL,
    standalone      TEXT    NOT NULL,
    answer          TEXT    NOT NULL,
    sources         TEXT    NOT NULL DEFAULT '[]',
    seconds         REAL,
    created_at      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_id);
"""


@dataclass(frozen=True)
class Conversation:
    id: int
    title: str                  # Empty when untitled.
    scope: list[str] | None     # None means all books.
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class Turn:
    id: int
    question: str
    standalone: str
    answer: str
    sources: list[dict[str, Any]]   # [{"book", "text", "score"}, ...]
    seconds: float | None
    created_at: float


@dataclass(frozen=True)
class StoreStats:
    conversations: int
    turns: int


@dataclass(frozen=True)
class ExportLabels:
    """Headings used in an exported conversation; the interface passes localized ones."""

    untitled: str = "Untitled conversation"
    scope: str = "Search scope"
    all_books: str = "All books"
    question: str = "Question"
    answer: str = "Answer"
    sources: str = "Sources"


DEFAULT_EXPORT_LABELS = ExportLabels()


def _format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _encode_scope(books: list[str] | None) -> str | None:
    return None if books is None else json.dumps(list(books), ensure_ascii=False)


class ConversationStore:
    def __init__(self, path: str = ":memory:", clock: Callable[[], float] = time.time) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- Conversations --------------------------------------------------------

    @staticmethod
    def _to_conversation(row: sqlite3.Row) -> Conversation:
        scope = json.loads(row["scope"]) if row["scope"] is not None else None
        return Conversation(row["id"], row["title"], scope, row["created_at"], row["updated_at"])

    def create_conversation(self, title: str = "", scope: list[str] | None = None) -> Conversation:
        now = self._clock()
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO conversations (title, scope, created_at, updated_at) VALUES (?,?,?,?)",
                (title, _encode_scope(scope), now, now),
            )
        return self._require_conversation(cursor.lastrowid)

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return self._to_conversation(row) if row else None

    def _require_conversation(self, conversation_id: int | None) -> Conversation:
        conversation = self.get_conversation(conversation_id) if conversation_id is not None else None
        if conversation is None:
            raise KeyError(f"Conversation not found: {conversation_id}")
        return conversation

    def list_conversations(self) -> list[Conversation]:
        """Return all conversations, most recently active first."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM conversations ORDER BY updated_at DESC, id DESC").fetchall()
        return [self._to_conversation(row) for row in rows]

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title.strip(), conversation_id))

    def set_scope(self, conversation_id: int, books: list[str] | None) -> None:
        """Set which books a conversation searches; None means all books."""
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET scope = ? WHERE id = ?", (_encode_scope(books), conversation_id))

    def delete_conversation(self, conversation_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    # -- Turns ----------------------------------------------------------------

    def add_turn(
        self,
        conversation_id: int,
        question: str,
        standalone: str,
        answer: str,
        sources: list[dict[str, Any]] | None = None,
        seconds: float | None = None,
    ) -> Turn:
        """Append a turn; an untitled conversation is titled after its first question."""
        conversation = self._require_conversation(conversation_id)
        sources = sources or []
        now = self._clock()
        title = conversation.title or truncate(" ".join(question.split()), TITLE_MAX_CHARS)

        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO turns (conversation_id, question, standalone, answer, sources, seconds, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (conversation_id, question, standalone, answer, json.dumps(sources, ensure_ascii=False), seconds, now),
            )
            self._db.execute(
                "UPDATE conversations SET updated_at = ?, title = ? WHERE id = ?", (now, title, conversation_id),
            )
        return Turn(cursor.lastrowid, question, standalone, answer, sources, seconds, now)

    def add_result(self, conversation_id: int, result: Any) -> Turn:
        """Store an ``istinbat.core.AskResult`` as a new turn."""
        return self.add_turn(
            conversation_id,
            result.question,
            result.standalone,
            result.answer,
            [asdict(source) for source in result.sources],
            result.total_seconds,
        )

    def turns(self, conversation_id: int) -> list[Turn]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM turns WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            ).fetchall()
        return [
            Turn(
                row["id"], row["question"], row["standalone"], row["answer"],
                json.loads(row["sources"]), row["seconds"], row["created_at"],
            )
            for row in rows
        ]

    def history_for(self, conversation_id: int, max_turns: int = 3, answer_chars: int = 500) -> ChatHistory:
        """Rebuild the engine's memory of a stored conversation (standalone questions, last turns)."""
        return ChatHistory.from_turns(
            [(turn.standalone, turn.answer) for turn in self.turns(conversation_id)],
            max_turns=max_turns,
            answer_chars=answer_chars,
        )

    # -- Data management ------------------------------------------------------

    def export_markdown(self, conversation_id: int, labels: ExportLabels = DEFAULT_EXPORT_LABELS) -> str:
        """Render a conversation as Markdown for export."""
        conversation = self._require_conversation(conversation_id)
        scope = labels.all_books if conversation.scope is None else ", ".join(conversation.scope) or "-"
        lines = [
            f"# {conversation.title or labels.untitled}",
            "",
            f"_{_format_time(conversation.created_at)}_",
            "",
            f"**{labels.scope}:** {scope}",
            "",
        ]
        for turn in self.turns(conversation_id):
            lines += ["---", "", f"### {labels.question}", "", turn.question, "",
                      f"### {labels.answer}", "", turn.answer, ""]
            books = list(dict.fromkeys(source["book"] for source in turn.sources))
            if books:
                lines += [f"**{labels.sources}:** {', '.join(books)}", ""]
        return "\n".join(lines).rstrip() + "\n"

    def delete_all(self) -> int:
        """Delete every conversation and its turns; returns how many conversations were removed."""
        with self._lock, self._db:
            count = self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            self._db.execute("DELETE FROM conversations")
        return count

    def purge_older_than(self, days: int) -> int:
        """Delete conversations idle for more than ``days`` days; zero or less disables purging."""
        if days <= 0:
            return 0
        cutoff = self._clock() - days * SECONDS_PER_DAY
        with self._lock, self._db:
            return self._db.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,)).rowcount

    def stats(self) -> StoreStats:
        with self._lock:
            conversations = self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            turns = self._db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        return StoreStats(conversations, turns)
