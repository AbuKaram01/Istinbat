# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rewrite follow-up questions into standalone questions."""

from __future__ import annotations

import re
from typing import Any

from .history import ChatHistory
from .language import ContentLanguage, detect_language
from .prompts import build_transcript, rewrite_prompt
from .safety import PromptGuard, neutralize
from .settings import MemoryConfig, RewriteMode

_LABEL = re.compile(
    r"^(?:السؤال(?:\s+المُعاد\s+صياغته|\s+المعاد\s+صياغته)?|سؤال"
    r"|(?:rewritten\s+|new\s+|standalone\s+)?question)\s*[:：]\s*",
    re.IGNORECASE,
)
_LATIN_TERM = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*")


def needs_rewrite(question: str, history: ChatHistory | None, config: MemoryConfig) -> bool:
    """Decide whether ``question`` should be rewritten.

    The first question of a conversation never is. In ``AUTO`` mode only short
    questions are, which is cheap but misjudges short standalone questions.
    """
    if history is None or not history.turns or config.rewrite_mode is RewriteMode.OFF:
        return False
    too_long_for_auto = len(question.split()) > config.rewrite_short_words
    return not (config.rewrite_mode is RewriteMode.AUTO and too_long_for_auto)


def rewrite_question(
    question: str,
    history: ChatHistory | None,
    config: MemoryConfig,
    llm: Any,
    guard: PromptGuard,
) -> str:
    """Return a standalone version of ``question`` using the conversation so far.

    Falls back to the original question when the model returns nothing or
    something suspiciously long (it answered instead of rewriting). In an Arabic
    question, English terms the model dropped are appended back.
    """
    if not needs_rewrite(question, history, config):
        return question

    language = detect_language(question)
    completion = llm.create_chat_completion(
        messages=rewrite_prompt(question, build_transcript(history.turns, language), language, guard),
        max_tokens=config.rewrite_max_tokens,
        temperature=0.0,
    )
    lines = completion["choices"][0]["message"]["content"].strip().splitlines()
    rewritten = neutralize(_LABEL.sub("", lines[0].strip())) if lines else ""

    if not rewritten or len(rewritten) > config.rewrite_max_chars:
        return question

    if language is not ContentLanguage.AR:
        return rewritten           # In an English question every word is Latin; nothing is a "term" to restore.
    dropped = [term for term in _LATIN_TERM.findall(question) if term.lower() not in rewritten.lower()]
    return f"{rewritten} {' '.join(dropped)}" if dropped else rewritten
