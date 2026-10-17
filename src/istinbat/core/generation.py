# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Answer generation with optional token streaming and cancellation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .progress import CancelCheck, TokenCallback


@dataclass
class Generation:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None   # Approximate (chunk count) when streaming.
    first_token_seconds: float | None = None
    cancelled: bool = False


def generate_answer(
    llm: Any,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    on_token: TokenCallback | None = None,
    cancel: CancelCheck | None = None,
) -> Generation:
    """Generate an answer, streaming it when ``on_token`` is given.

    Without ``on_token`` a single blocking call returns exact token usage.
    With it, each fragment is delivered immediately and ``cancel`` is checked
    between fragments. Reading the prompt itself cannot be interrupted.
    """
    if on_token is None:
        return _generate_blocking(llm, messages, max_tokens, temperature)
    return _generate_streaming(llm, messages, max_tokens, temperature, on_token, cancel)


def _generate_blocking(llm: Any, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> Generation:
    completion = llm.create_chat_completion(messages=messages, max_tokens=max_tokens, temperature=temperature)
    usage = completion.get("usage") or {}
    return Generation(
        text=completion["choices"][0]["message"]["content"].strip(),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )


def _generate_streaming(
    llm: Any,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    on_token: TokenCallback,
    cancel: CancelCheck | None,
) -> Generation:
    started = time.perf_counter()
    stream = llm.create_chat_completion(
        messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True,
    )
    fragments: list[str] = []
    first_token_seconds: float | None = None
    cancelled = False

    try:
        for chunk in stream:
            if cancel is not None and cancel():
                cancelled = True
                break
            fragment = (chunk["choices"][0].get("delta") or {}).get("content")
            if not fragment:
                continue
            if first_token_seconds is None:
                first_token_seconds = time.perf_counter() - started
            fragments.append(fragment)
            on_token(fragment)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()

    return Generation(
        text="".join(fragments).strip(),
        completion_tokens=len(fragments),
        first_token_seconds=first_token_seconds,
        cancelled=cancelled,
    )
