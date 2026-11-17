# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

import pytest
from conftest import BOOK_A, BOOK_B, FakeCollection, FakeEmbedder

from istinbat.core import BookStatus, ProgressKey, index_library, rebuild_library, remove_book, scan_library
from istinbat.core.indexer import indexed_book_names
from istinbat.core.manifest import Manifest


def run(settings, **overrides):
    overrides.setdefault("embedder", FakeEmbedder())
    overrides.setdefault("collection", FakeCollection())
    return index_library(settings, **overrides), overrides["collection"], overrides["embedder"]


def test_new_books_are_indexed_with_monotonic_progress(settings, write_book):
    path = write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    updates = []
    report, collection, _ = run(settings, progress=updates.append)

    fractions = [update.fraction for update in updates]
    assert report.new_books == 2 and report.chunks_added == collection.count() > 0
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    assert updates[-1].key is ProgressKey.INDEX_DONE
    assert Manifest.load(settings.paths.manifest_file).digest_of(path)


def test_encoding_progress_carries_book_and_counts(settings, write_book):
    write_book("a", BOOK_A)
    updates = []
    run(settings, progress=updates.append)
    encoding = [u for u in updates if u.key is ProgressKey.INDEX_ENCODING]
    assert encoding and encoding[-1].args["book"] == "a"
    assert encoding[-1].args["done"] == encoding[-1].args["total"]


def test_second_run_does_nothing(settings, write_book):
    write_book("a", BOOK_A)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)
    calls = len(embedder.calls)

    report, _, _ = run(settings, collection=collection, embedder=embedder)
    assert report.nothing_to_do and report.unchanged_books == 1
    assert len(embedder.calls) == calls


def test_modified_book_replaces_only_its_own_chunks(settings, write_book):
    write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)
    book_b_chunks = sum(1 for _, meta in collection.rows.values() if meta["source"] == "b")

    write_book("a", BOOK_A[:600] + " تعديل جديد في نص الكتاب كله هنا.")
    report, _, _ = run(settings, collection=collection, embedder=embedder)

    assert report.modified_books == 1
    sources = [meta["source"] for _, meta in collection.rows.values()]
    assert sources.count("b") == book_b_chunks
    assert all("رقم 39" not in doc for doc, meta in collection.rows.values() if meta["source"] == "a")


def test_removed_book_is_purged_and_manifest_saved(settings, write_book):
    path = write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)

    os.remove(path)
    report, _, _ = run(settings, collection=collection, embedder=embedder)
    assert report.removed_books == 1
    assert {meta["source"] for _, meta in collection.rows.values()} == {"b"}
    assert Manifest.load(settings.paths.manifest_file).digest_of(path) is None


def test_cancel_keeps_only_finished_books(settings, write_book):
    write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    embedder = FakeEmbedder()
    report, collection, _ = run(settings, embedder=embedder, cancel=lambda: len(embedder.calls) >= 1)

    manifest = Manifest.load(settings.paths.manifest_file)
    assert report.cancelled and len(manifest) == 1
    finished = os.path.splitext(os.path.basename(next(iter(manifest.known_paths()))))[0]
    assert {meta["source"] for _, meta in collection.rows.values()} == {finished}


def test_missing_books_folder_raises(settings):
    settings.paths.books_dir += "/missing"
    with pytest.raises(FileNotFoundError):
        index_library(settings, embedder=FakeEmbedder(), collection=FakeCollection())


def test_scan_library_reports_statuses(settings, write_book):
    write_book("a", BOOK_A)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)
    write_book("b", BOOK_B)
    write_book("a", BOOK_A + " إضافة جديدة في آخر الكتاب هنا.")

    statuses = {book.name: book.status for book in scan_library(settings)}
    assert statuses == {"a": BookStatus.MODIFIED, "b": BookStatus.NEW}


def test_changing_chunking_settings_marks_books_modified(settings, write_book):
    write_book("a", BOOK_A)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)
    assert {book.status for book in scan_library(settings)} == {BookStatus.INDEXED}

    settings.indexing.max_chunk_chars = 800
    assert {book.status for book in scan_library(settings)} == {BookStatus.MODIFIED}
    report, _, _ = run(settings, collection=collection, embedder=embedder)
    assert report.modified_books == 1


def test_rebuild_wipes_orphans_and_reindexes_everything(settings, write_book):
    write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)
    original_ids, original_calls = set(collection.rows), len(embedder.calls)

    collection.upsert(["orphan"], [[0]], ["stale"], [{"source": "ghost", "norm_text": "x"}])
    report = rebuild_library(settings, embedder=embedder, collection=collection)

    assert "orphan" not in collection.rows
    assert set(collection.rows) == original_ids
    assert report.new_books == 2 and len(embedder.calls) > original_calls
    assert {book.status for book in scan_library(settings)} == {BookStatus.INDEXED}


# -- Removing a book ----------------------------------------------------------

def test_removing_a_book_drops_its_passages_and_manifest_entry_but_keeps_the_others(settings, write_book):
    path = write_book("a", BOOK_A)
    other = write_book("b", BOOK_B)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)

    assert remove_book(settings, path, collection=collection) is True

    assert {meta["source"] for _, meta in collection.rows.values()} == {"b"}
    manifest = Manifest.load(settings.paths.manifest_file)
    assert manifest.digest_of(path) is None and manifest.digest_of(other)
    assert indexed_book_names(settings) == ["b"]


def test_removing_a_book_leaves_its_file_which_then_shows_as_new_and_can_be_indexed_again(settings, write_book):
    path = write_book("a", BOOK_A)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)
    remove_book(settings, path, collection=collection)

    assert os.path.exists(path)
    assert {book.name: book.status for book in scan_library(settings)} == {"a": BookStatus.NEW}
    report, _, _ = run(settings, collection=collection, embedder=embedder)
    assert report.new_books == 1 and collection.count() > 0


def test_after_the_file_is_deleted_too_the_next_indexing_run_has_nothing_left_to_do(settings, write_book):
    path = write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)

    remove_book(settings, path, collection=collection)
    os.remove(path)
    report, _, _ = run(settings, collection=collection, embedder=embedder)

    assert report.nothing_to_do and report.removed_books == 0


def test_removing_a_book_that_is_not_indexed_changes_nothing(settings, write_book):
    write_book("a", BOOK_A)
    write_book("b", BOOK_B)
    collection = FakeCollection()
    index_library(settings, embedder=FakeEmbedder(), collection=collection)
    added_later = write_book("c", BOOK_B)
    before = dict(collection.rows)

    assert remove_book(settings, added_later, collection=collection) is False
    assert collection.rows == before and len(Manifest.load(settings.paths.manifest_file)) == 2


def test_removing_a_book_forgets_a_namesake_in_another_folder_so_it_is_indexed_again(settings, write_book):
    first = write_book("a", BOOK_A)
    second = os.path.join(settings.paths.books_dir, "sub", "a.txt")
    os.makedirs(os.path.dirname(second))
    with open(second, "w", encoding="utf-8") as handle:
        handle.write(BOOK_B)
    collection, embedder = FakeCollection(), FakeEmbedder()
    run(settings, collection=collection, embedder=embedder)

    remove_book(settings, first, collection=collection)

    assert collection.count() == 0                                  # The passages are stored under the shared name.
    assert len(Manifest.load(settings.paths.manifest_file)) == 0
    report, _, _ = run(settings, collection=collection, embedder=embedder)
    assert report.new_books == 2


def test_removing_a_book_does_not_touch_a_namesake_when_the_book_itself_was_not_indexed(settings, write_book):
    indexed = write_book("a", BOOK_A)
    collection = FakeCollection()
    index_library(settings, embedder=FakeEmbedder(), collection=collection)
    unindexed = os.path.join(settings.paths.books_dir, "sub", "a.txt")

    assert remove_book(settings, unindexed, collection=collection) is False
    assert collection.count() > 0 and Manifest.load(settings.paths.manifest_file).digest_of(indexed)


def test_removing_a_book_without_a_given_collection_opens_the_store_itself(settings, write_book, monkeypatch):
    path = write_book("a", BOOK_A)
    collection = FakeCollection()
    index_library(settings, embedder=FakeEmbedder(), collection=collection)
    monkeypatch.setattr("istinbat.core.indexer.open_collection", lambda _settings: collection)

    assert remove_book(settings, path) is True and collection.count() == 0
