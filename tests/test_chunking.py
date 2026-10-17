# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from istinbat.core import IndexingConfig
from istinbat.core.chunking import build_chunks
from istinbat.core.sentences import split_sentences

TEXT = " ".join(f"هذه هي الجملة رقم {i} من الكتاب وفيها كلام كثير عن الموضوع." for i in range(80))


def test_chunks_respect_size_and_have_unique_ids():
    config = IndexingConfig()
    chunks = build_chunks(TEXT, "/books/book.txt", config)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= config.max_chunk_chars + 200 for chunk in chunks)
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert all(chunk.source == "book" for chunk in chunks)


def test_overlap_repeats_the_last_sentences_of_the_previous_chunk():
    chunks = build_chunks(TEXT, "a.txt", IndexingConfig())
    first = split_sentences(chunks[0].text, 10)
    second = split_sentences(chunks[1].text, 10)
    assert first[-2:] == second[:2]


def test_zero_overlap_and_blank_input():
    assert len(build_chunks(TEXT, "a.txt", IndexingConfig(overlap_sentences=0))) >= 2
    assert build_chunks("   \n  ", "a.txt", IndexingConfig()) == []


def test_a_very_short_text_is_kept_rather_than_dropped():
    chunks = build_chunks("قصير", "a.txt", IndexingConfig())
    assert [chunk.text for chunk in chunks] == ["قصير"]


def test_digits_stay_attached_to_surrounding_text():
    chunk = build_chunks("وقع الحدث سنة 2024م في المدينة الكبيرة.", "a.txt", IndexingConfig())[0]
    assert "2024م" in chunk.text


def test_normalized_text_differs_from_display_text():
    chunk = build_chunks("المدرسة الكبيرة أنشئت قديماً جداً.", "a.txt", IndexingConfig())[0]
    assert "ة" in chunk.text and "ة" not in chunk.normalized_text
