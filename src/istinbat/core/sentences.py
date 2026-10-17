# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sentence splitting for Arabic and English text."""

from __future__ import annotations

import re

# A sentence ends at terminal punctuation (plus closing quotes or brackets) that is
# followed by whitespace or the end of the text. A dot inside "3.14" or "node.js"
# is therefore never a boundary. Text with no punctuation at all stays one sentence.
_SENTENCE = re.compile(r"""\S.*?(?:[.!?؟؛…]+["'”’)\]»]*(?=\s|$)|$)""", re.DOTALL)


def split_sentences(text: str, min_chars: int) -> list[str]:
    """Split ``text`` into sentences, merging fragments shorter than ``min_chars`` with their neighbours.

    Short fragments ("Yes.", "e.g.", "1.") are joined onto the next sentence, and a
    short trailing fragment onto the previous one, so no text is lost.
    """
    sentences: list[str] = []
    pending = ""
    for match in _SENTENCE.finditer(text):
        fragment = match.group().strip()
        if not fragment:
            continue
        pending = f"{pending} {fragment}" if pending else fragment
        if len(pending) >= min_chars:
            sentences.append(pending)
            pending = ""
    if pending:
        if sentences:
            sentences[-1] = f"{sentences[-1]} {pending}"
        else:
            sentences.append(pending)
    return sentences
