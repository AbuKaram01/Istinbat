# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tokenization for keyword search over Arabic, English and mixed text."""

from __future__ import annotations

import re

from .arabic import stem_arabic

_TOKEN = re.compile(r"\w+(?:['’]\w+)*")
_ARABIC_LETTER = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_POSSESSIVE = re.compile(r"['’]s$")
_MIN_ENGLISH_STEM = 3


def stem_english(word: str) -> str:
    """Light, rule-based English stemming: plurals, "-ed" and "-ing".

    Deliberately simple. Keyword search only needs "indexes" and "indexing" to
    meet "index", and the vector search covers real semantic matching.
    """
    word = _POSSESSIVE.sub("", word)
    for suffix, replacement, minimum_stem in (
        ("sses", "ss", 2),
        ("ies", "y", 2),
        ("ing", "", _MIN_ENGLISH_STEM),
        ("ed", "", _MIN_ENGLISH_STEM),
        ("es", "", _MIN_ENGLISH_STEM),
        ("s", "", _MIN_ENGLISH_STEM),
    ):
        if word.endswith(suffix) and not word.endswith("ss") and len(word) - len(suffix) >= minimum_stem:
            return word[: -len(suffix)] + replacement
    return word


def tokenize(text: str) -> list[str]:
    """Split normalized text into search tokens.

    Arabic words lose their common prefixes and suffixes; every other word is
    lowercased and lightly stemmed. Expects Arabic already normalized with
    ``normalize_arabic``.
    """
    tokens = []
    for word in _TOKEN.findall(text):
        stem = stem_arabic(word) if _ARABIC_LETTER.search(word) else stem_english(word.lower())
        if stem:
            tokens.append(stem)
    return tokens
