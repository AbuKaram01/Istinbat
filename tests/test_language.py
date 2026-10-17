# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import pytest

from istinbat.core import AnswerLanguage, ContentLanguage, detect_language, resolve_answer_language


@pytest.mark.parametrize(("text", "expected"), [
    ("ما هي المعلومات؟", ContentLanguage.AR),
    ("What is information?", ContentLanguage.EN),
    ("ما هي المعلومات Information؟", ContentLanguage.AR),        # Mostly Arabic letters.
    ("Explain the term الاستنباط in detail", ContentLanguage.EN),  # Mostly Latin letters.
    ("اشرح لي كيف يعمل Docker", ContentLanguage.AR),
])
def test_detection_follows_the_majority_script(text, expected):
    assert detect_language(text) is expected


def test_text_without_letters_uses_the_fallback():
    assert detect_language("12345 ?!") is ContentLanguage.AR
    assert detect_language("", fallback=ContentLanguage.EN) is ContentLanguage.EN


def test_automatic_answer_language_follows_the_question():
    assert resolve_answer_language(AnswerLanguage.AUTO, "What is RAG?") is ContentLanguage.EN
    assert resolve_answer_language(AnswerLanguage.AUTO, "ما هو RAG؟") is ContentLanguage.AR


def test_a_forced_answer_language_ignores_the_question():
    assert resolve_answer_language(AnswerLanguage.ENGLISH, "ما هو RAG؟") is ContentLanguage.EN
    assert resolve_answer_language(AnswerLanguage.ARABIC, "What is RAG?") is ContentLanguage.AR
