# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from istinbat.core.arabic import normalize_arabic, stem_arabic


def test_normalize_unifies_letters_and_strips_marks():
    assert normalize_arabic("أَحْمَد إلى آخِرِه") == "احمد الي اخره"
    assert normalize_arabic("مدرسة") == "مدرسه"
    assert normalize_arabic("كـــتاب") == "كتاب"


def test_stemming_strips_a_prefix_and_a_suffix():
    assert stem_arabic("والكتب") == "كتب"
    assert stem_arabic("المفيده") == "مفيد"


def test_stemming_keeps_short_words_intact():
    assert stem_arabic("في") == "في"
    assert stem_arabic("ال") == "ال"
