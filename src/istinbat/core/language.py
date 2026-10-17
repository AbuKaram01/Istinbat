# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Which language a piece of text is written in, for choosing prompts and answer language."""

from __future__ import annotations

import re
from enum import Enum

from .settings import AnswerLanguage

_ARABIC_LETTER = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


class ContentLanguage(str, Enum):
    """A language the books, questions and answers can be in."""

    AR = "ar"
    EN = "en"


def detect_language(text: str, fallback: ContentLanguage = ContentLanguage.AR) -> ContentLanguage:
    """Guess the language by comparing how many Arabic and Latin letters ``text`` has.

    A mixed question such as "ما هي المعلومات Information؟" counts as Arabic because
    most of its letters are Arabic. Text with no letters at all returns ``fallback``.
    """
    arabic = len(_ARABIC_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    if arabic == latin == 0:
        return fallback
    return ContentLanguage.AR if arabic >= latin else ContentLanguage.EN


def resolve_answer_language(preference: AnswerLanguage, question: str) -> ContentLanguage:
    """Pick the language to answer in: forced by the user, or the question's own language."""
    if preference is AnswerLanguage.ARABIC:
        return ContentLanguage.AR
    if preference is AnswerLanguage.ENGLISH:
        return ContentLanguage.EN
    return detect_language(question)
