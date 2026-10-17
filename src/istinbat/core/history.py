# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""In-memory conversation history used to resolve follow-up questions."""

from __future__ import annotations

from dataclasses import dataclass, field

ELLIPSIS = "…"


def truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters and append an ellipsis if it was shortened."""
    return text if len(text) <= limit else text[:limit].rstrip() + ELLIPSIS


@dataclass
class ChatHistory:
    """The last ``max_turns`` (standalone question, answer) pairs of a conversation.

    Questions are stored after rewriting so later pronouns resolve against a
    complete question. Durable storage lives in ``istinbat.storage``.
    """

    max_turns: int = 3
    answer_chars: int = 500
    turns: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_turns(
        cls,
        turns: list[tuple[str, str]],
        max_turns: int = 3,
        answer_chars: int = 500,
    ) -> ChatHistory:
        """Rebuild a history from persisted turns, keeping only the most recent ones."""
        history = cls(max_turns=max_turns, answer_chars=answer_chars)
        for question, answer in turns:
            history.add(question, answer)
        return history

    def add(self, question: str, answer: str) -> None:
        self.turns.append((question, answer))
        self.turns = self.turns[-self.max_turns:] if self.max_turns > 0 else []

    def clear(self) -> None:
        self.turns = []

    def as_messages(self) -> list[dict[str, str]]:
        """Return previous turns as alternating chat messages for the answer prompt."""
        messages: list[dict[str, str]] = []
        for question, answer in self.turns:
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": truncate(answer, self.answer_chars)})
        return messages
