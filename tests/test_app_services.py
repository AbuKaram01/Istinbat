# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The state the first-run guide and the lazy model loading rely on, without any interface."""

from types import SimpleNamespace

import pytest
from conftest import FakeCollection

from istinbat.core.manifest import Manifest
from istinbat.core.settings import Settings, load_settings
from istinbat.services import AppServices, Worker


@pytest.fixture
def services(tmp_path):
    settings = Settings()
    settings.paths.models_dir = str(tmp_path / "models")
    settings.paths.manifest_file = str(tmp_path / "manifest.json")
    settings.paths.conversations_db = str(tmp_path / "c.db")
    worker = Worker([].append)
    created = AppServices(settings, worker, settings_path=tmp_path / "settings.json")
    yield created
    worker.shutdown(1)


def choose_all_models(services, tmp_path):
    for attribute in ("embedder_model", "reranker_model", "llm_model"):
        path = tmp_path / attribute
        path.write_bytes(b"x")
        setattr(services.settings.paths, attribute, str(path))


def test_a_new_installation_without_models_is_shown_the_guide(services):
    assert services.should_show_welcome()


def test_an_installation_that_already_has_its_models_never_sees_the_guide(services, tmp_path):
    choose_all_models(services, tmp_path)

    assert not services.should_show_welcome()
    assert services.settings.app.welcome_done                       # Recorded, so deleting a model later is quiet.
    assert load_settings(tmp_path / "settings.json").app.welcome_done


def test_the_guide_is_not_shown_again_once_it_has_been_dealt_with(services, tmp_path):
    services.mark_welcome_done()

    assert not services.should_show_welcome()
    assert load_settings(tmp_path / "settings.json").app.welcome_done


def test_marking_the_guide_done_twice_saves_once(services, tmp_path):
    services.mark_welcome_done()
    saved = (tmp_path / "settings.json").stat().st_mtime_ns
    services.mark_welcome_done()

    assert (tmp_path / "settings.json").stat().st_mtime_ns == saved


def test_the_indexed_books_are_listed_from_the_manifest(services, tmp_path):
    assert services.indexed_books() == []

    manifest = Manifest(services.settings.paths.manifest_file)
    manifest.record(str(tmp_path / "Beta.txt"), "x")
    manifest.record(str(tmp_path / "Alpha.txt"), "y")
    manifest.save()

    assert services.indexed_books() == ["Alpha", "Beta"]
    assert services.engine is None                                  # Listing the books loaded nothing.


def test_clearing_a_load_error_lets_the_next_use_try_again(services):
    services.load_error = RuntimeError("no models")
    services.clear_load_error()

    assert services.load_error is None


def test_removing_a_book_without_the_engine_opens_the_vector_store_on_its_own(services, tmp_path, monkeypatch):
    collection = FakeCollection()
    collection.upsert(["1", "2"], [[0], [0]], ["x", "y"], [{"source": "Alpha"}, {"source": "Beta"}])
    monkeypatch.setattr("istinbat.core.indexer.open_collection", lambda _settings: collection)
    manifest = Manifest(services.settings.paths.manifest_file)
    manifest.record(str(tmp_path / "Alpha.txt"), "x")
    manifest.record(str(tmp_path / "Beta.txt"), "y")
    manifest.save()

    assert services.remove_book(str(tmp_path / "Alpha.txt")) is True

    assert [meta["source"] for _, meta in collection.rows.values()] == ["Beta"]
    assert services.indexed_books() == ["Beta"] and services.engine is None


def test_removing_a_book_goes_through_the_loaded_engine_so_its_search_index_follows(services):
    removed = []
    services.engine = SimpleNamespace(remove_book=lambda path: removed.append(path) or True)

    assert services.remove_book("/books/Alpha.txt") is True
    assert removed == ["/books/Alpha.txt"]
