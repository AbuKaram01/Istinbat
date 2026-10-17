# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Arabic text processing: normalization and light stemming."""

from __future__ import annotations

import re

_ALEF_VARIANTS = re.compile(r"[أإآٱ]")
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")
_LAM_ALEF_LIGATURES = re.compile(r"[ﻻﻷﻹﻵ]")

# Prefixes are ordered longest first so the longest match wins.
_PREFIXES = re.compile(r"^(?:وال|فال|بال|كال|لل|ال|و|ف|ب|ك|ل|س)")
_SUFFIXES = re.compile(r"(?:تان|تين|ها|هم|هن|كم|كن|نا|ني|وا|ون|ين|ان|ات|ه)$")
_MIN_STEM_LENGTH = 2


def normalize_arabic(text: str) -> str:
    """Unify alef, teh marbuta and yeh variants and strip diacritics and tatweel."""
    text = _ALEF_VARIANTS.sub("ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي").replace("ـ", "")
    text = _DIACRITICS.sub("", text)
    return _LAM_ALEF_LIGATURES.sub("لا", text)


def preprocess(text: str) -> str:
    """Single entry point for text normalization; add future steps here only."""
    return normalize_arabic(text)


def stem_arabic(word: str) -> str:
    """Strip common prefixes and suffixes from a normalized Arabic word.

    Stems shorter than two characters are rejected to avoid over-stripping.
    """
    stem = word
    prefix = _PREFIXES.match(stem)
    if prefix and len(stem) - prefix.end() >= _MIN_STEM_LENGTH:
        stem = stem[prefix.end():]

    suffix = _SUFFIXES.search(stem)
    if suffix and suffix.start() >= _MIN_STEM_LENGTH:
        stem = stem[:suffix.start()]
    return stem
