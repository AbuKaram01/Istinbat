# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from istinbat.core import IndexingConfig
from istinbat.core import manifest as manifest_module
from istinbat.core.books import BookFile, book_name, load_book_files
from istinbat.core.manifest import Manifest, classify, content_digest


def test_book_name_drops_directory_and_extension():
    assert book_name("/a/b/My Book.txt") == "My Book"
    assert BookFile("/a/x.txt", "").name == "x"


def test_load_book_files_reads_only_txt_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "sub" / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignored", encoding="utf-8")
    assert [book.content for book in load_book_files(str(tmp_path))] == ["b", "a"]


def test_digest_depends_on_chunking_settings_and_version(monkeypatch):
    config = IndexingConfig()
    digest = content_digest("abc", config)
    assert content_digest("abc", IndexingConfig(max_chunk_chars=800)) != digest
    assert content_digest("abc", IndexingConfig(overlap_sentences=0)) != digest
    monkeypatch.setattr(manifest_module, "CHUNKING_VERSION", "other")
    assert content_digest("abc", config) != digest


def test_classify_splits_new_modified_and_unchanged(tmp_path):
    config = IndexingConfig()
    manifest = Manifest(str(tmp_path / "m.json"))
    manifest.record("m", "stale-digest")
    manifest.record("u", content_digest("same", config))

    result = classify(
        [BookFile("n", "x"), BookFile("m", "changed"), BookFile("u", "same")], manifest, config,
    )
    assert [b.path for b in result.new] == ["n"]
    assert [b.path for b in result.modified] == ["m"]
    assert [b.path for b in result.unchanged] == ["u"]
    assert [b.path for b in result.pending] == ["n", "m"]


def test_manifest_persists_and_survives_corruption(tmp_path):
    path = str(tmp_path / "sub" / "manifest.json")
    manifest = Manifest(path)
    manifest.record("book.txt", "digest")
    manifest.save()

    reloaded = Manifest.load(path)
    assert reloaded.digest_of("book.txt") == "digest" and len(reloaded) == 1
    reloaded.forget("book.txt")
    assert reloaded.known_paths() == set()

    (tmp_path / "broken.json").write_text("{oops", encoding="utf-8")
    assert len(Manifest.load(str(tmp_path / "broken.json"))) == 0
