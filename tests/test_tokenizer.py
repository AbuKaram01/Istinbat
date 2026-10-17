# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from istinbat.core.arabic import normalize_arabic
from istinbat.core.tokenizer import stem_english, tokenize


def test_arabic_words_lose_prefixes_and_suffixes():
    assert tokenize(normalize_arabic("والكتب المفيدة؟")) == ["كتب", "مفيد"]


def test_english_words_are_lowercased_and_lightly_stemmed():
    assert tokenize("Indexing Databases, and Queries!") == ["index", "databas", "and", "query"]


def test_mixed_text_uses_the_right_rule_for_each_word():
    assert tokenize(normalize_arabic("قاعدة البيانات Databases")) == ["قاعد", "بيان", "databas"]


def test_punctuation_and_empty_input_yield_no_tokens():
    assert tokenize("؟! ... ,") == []
    assert tokenize("") == []


def test_possessives_and_internal_apostrophes_stay_one_token():
    assert tokenize("The model's don't") == ["the", "model", "don't"]


def test_stemming_matches_plural_and_gerund_forms_to_the_base_word():
    assert stem_english("indexes") == stem_english("index") == "index"
    assert stem_english("running") == "runn"
    assert stem_english("queries") == "query"
    assert stem_english("class") == "class"          # "ss" endings are not plurals.
    assert stem_english("is") == "is"                # Too short to strip.


def test_digits_are_kept_as_tokens():
    assert tokenize("version 3 of 2024") == ["version", "3", "of", "2024"]
