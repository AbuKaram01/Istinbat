# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Deleting a book from the library page, driven through the real interface with a stand-in engine."""

import os
from pathlib import Path

import pytest

os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent"

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk
except (ValueError, ImportError):
    pytest.skip("GTK 4 / libadwaita are not installed", allow_module_level=True)

if not Gtk.init_check():
    pytest.skip("no display available", allow_module_level=True)

from conftest import FakeCollection
from gui_fakes import SAMPLE_BOOKS
from gui_support import build_app, pump, start

from istinbat.gui import library_page


@pytest.fixture
def make_app(tmp_path):
    created = []

    def factory(**options):
        app, services, engine = build_app(tmp_path / f"run{len(created)}", **options)
        created.append((app, services))
        return app, services, engine

    yield factory

    for app, services in created:
        for window in list(app.get_windows()):
            window.destroy()
        services.worker.shutdown(timeout=1)
    Gtk.Widget.set_default_direction(Gtk.TextDirection.LTR)


@pytest.fixture
def toasts(monkeypatch):
    """Collect the messages the window would show as toasts."""
    shown = []
    monkeypatch.setattr("istinbat.gui.window.MainWindow.show_toast", lambda _window, message: shown.append(message))
    return shown


@pytest.fixture
def trash_available(monkeypatch):
    """Pretend the system has a Trash and record what is sent to it, so no test depends on the machine's Trash."""
    sent = []
    monkeypatch.setattr(library_page, "_can_trash", lambda _path: True)
    monkeypatch.setattr(library_page, "_discard_file", lambda path, trash: sent.append((path, trash)))
    return sent


def open_library(app, services, **options):
    window = start(app, services, load=options.get("load", True))
    window.open_library()
    pump(0.4)
    return window


def book_path(services, name):
    return str(Path(services.settings.paths.books_dir) / f"{name}.txt")


def isolated(name):
    """A book name as the interface puts it into a sentence: isolated, so its script cannot reorder the text."""
    return f"\u2068{name}\u2069"


def names_listed(window):
    names, row = [], window._library._list.get_first_child()
    while row is not None:
        names.append(row.get_title())
        row = row.get_next_sibling()
    return names


def delete(window, name):
    """Press a book's delete button and accept the confirmation, which closes as it does for a real click."""
    window._library._delete_buttons[names_listed(window).index(name)].emit("clicked")
    pump(0.2)
    confirmation = window.get_visible_dialog()
    confirmation.emit("response", "confirm")
    confirmation.force_close()
    pump(1.0, until=lambda: not window.is_busy)
    pump(0.4)


# -- the button and the confirmation ---------------------------------------------------------------

def test_every_book_row_has_a_delete_button_named_after_its_book(make_app):
    app, services, _ = make_app()
    window = open_library(app, services)
    buttons = window._library._delete_buttons

    assert len(buttons) == len(SAMPLE_BOOKS)
    tooltips = sorted(button.get_tooltip_text() for button in buttons)
    assert tooltips == sorted(f"Delete “{isolated(name)}”" for name in SAMPLE_BOOKS)


def test_the_confirmation_names_the_book_and_says_the_file_goes_to_the_trash(make_app, trash_available):
    app, services, engine = make_app()
    window = open_library(app, services)
    window._library._delete_buttons[0].emit("clicked")
    pump(0.3)
    dialog = window.get_visible_dialog()

    assert isolated(names_listed(window)[0]) in dialog.get_heading() and dialog.get_heading().startswith("Delete")
    assert "moved to the Trash" in dialog.get_body()
    assert trash_available == [] and engine.removed == []                       # Nothing happens before the answer.


def test_without_a_trash_the_confirmation_says_the_file_is_deleted_permanently(make_app, monkeypatch):
    monkeypatch.setattr(library_page, "_can_trash", lambda _path: False)
    app, services, _ = make_app()
    window = open_library(app, services)
    window._library._delete_buttons[0].emit("clicked")
    pump(0.3)

    assert "deleted permanently" in window.get_visible_dialog().get_body()


def test_cancelling_the_confirmation_keeps_the_book(make_app, trash_available):
    app, services, engine = make_app()
    window = open_library(app, services)
    window._library._delete_buttons[0].emit("clicked")
    pump(0.3)
    dialog = window.get_visible_dialog()
    dialog.emit("response", "cancel")
    dialog.force_close()
    pump(0.3)

    assert trash_available == [] and engine.removed == [] and len(names_listed(window)) == len(SAMPLE_BOOKS)


# -- deleting --------------------------------------------------------------------------------------

def test_deleting_moves_the_file_to_the_trash_and_takes_the_book_out_of_the_index(make_app, trash_available, toasts):
    app, services, engine = make_app()
    window = open_library(app, services)
    name = names_listed(window)[0]
    delete(window, name)

    assert trash_available == [(book_path(services, name), True)]
    assert engine.removed == [book_path(services, name)]
    assert toasts == [f"“{isolated(name)}” deleted"]
    assert not window.is_busy


def test_a_permanently_deleted_file_is_gone_and_the_list_updates(make_app, monkeypatch, toasts):
    monkeypatch.setattr(library_page, "_can_trash", lambda _path: False)
    app, services, engine = make_app()
    window = open_library(app, services)
    name = names_listed(window)[0]
    delete(window, name)

    assert not os.path.exists(book_path(services, name))
    assert name not in names_listed(window) and len(names_listed(window)) == len(SAMPLE_BOOKS) - 1
    assert engine.removed == [book_path(services, name)]


def test_deleting_the_last_book_shows_the_empty_library(make_app, monkeypatch, toasts):
    monkeypatch.setattr(library_page, "_can_trash", lambda _path: False)
    app, services, _ = make_app()
    window = open_library(app, services)
    for name in list(names_listed(window)):
        delete(window, name)

    assert names_listed(window) == []
    assert window._library._stack.get_visible_child_name() == "empty"


def test_a_book_that_is_already_gone_from_the_folder_is_still_taken_out_of_the_index(make_app, monkeypatch, toasts):
    monkeypatch.setattr(library_page, "_can_trash", lambda _path: False)
    app, services, engine = make_app()
    window = open_library(app, services)
    name = names_listed(window)[0]
    os.remove(book_path(services, name))                                        # Removed by hand after the list drew.
    delete(window, name)

    assert engine.removed == [book_path(services, name)] and toasts == [f"“{isolated(name)}” deleted"]


def test_deleting_works_before_the_models_are_loaded_and_loads_none(make_app, monkeypatch, toasts, trash_available):
    collection = FakeCollection()
    collection.upsert(
        [name for name in SAMPLE_BOOKS], [[0]] * len(SAMPLE_BOOKS), ["text"] * len(SAMPLE_BOOKS),
        [{"source": name} for name in SAMPLE_BOOKS],
    )
    monkeypatch.setattr("istinbat.core.indexer.open_collection", lambda _settings: collection)
    app, services, engine = make_app()
    window = open_library(app, services, load=False)
    name = names_listed(window)[0]
    delete(window, name)

    assert engine.loads == 0 and services.engine is None and engine.removed == []
    assert {meta["source"] for _, meta in collection.rows.values()} == set(SAMPLE_BOOKS) - {name}
    assert name not in services.indexed_books()
    assert name not in window._chat.scope_button._checks                        # The scope list follows.


def test_the_scope_list_drops_a_deleted_book(make_app, trash_available, toasts):
    app, services, _ = make_app()
    window = open_library(app, services)
    name = names_listed(window)[0]
    services.engine.books = lambda: [book for book in SAMPLE_BOOKS if book != name]
    delete(window, name)

    assert name not in window._chat.scope_button._checks


# -- while it runs, and when it fails --------------------------------------------------------------

def test_the_library_and_the_question_box_are_locked_while_a_book_is_being_deleted(make_app, trash_available, toasts):
    app, services, engine = make_app()
    engine.remove_delay = 0.6
    window = open_library(app, services)
    window._library._delete_buttons[0].emit("clicked")
    pump(0.3)
    confirmation = window.get_visible_dialog()
    confirmation.emit("response", "confirm")
    confirmation.force_close()
    pump(0.2)

    assert window.is_busy
    assert not any(button.get_sensitive() for button in window._library._delete_buttons)
    assert not window._library._index_button.get_sensitive() and not window._chat._entry.get_sensitive()

    pump(5, until=lambda: not window.is_busy)
    pump(0.4)
    assert all(button.get_sensitive() for button in window._library._delete_buttons)
    assert window._library._index_button.get_sensitive() and window._chat._entry.get_sensitive()


def test_a_book_cannot_be_deleted_while_another_job_runs(make_app, trash_available):
    app, services, engine = make_app()
    window = open_library(app, services)
    window.set_busy("indexing")
    window._library._delete_buttons[0].emit("clicked")
    pump(0.3)

    assert window.get_visible_dialog() is None and trash_available == [] and engine.removed == []


def test_a_file_that_cannot_be_deleted_is_reported_and_the_index_is_left_alone(make_app, monkeypatch, toasts):
    def refuse(_path, _trash):
        raise PermissionError("Permission denied")

    monkeypatch.setattr(library_page, "_can_trash", lambda _path: True)
    monkeypatch.setattr(library_page, "_discard_file", refuse)
    app, services, engine = make_app()
    window = open_library(app, services)
    name = names_listed(window)[0]
    delete(window, name)

    assert toasts == [f"Couldn’t delete “{isolated(name)}”: Permission denied"]
    assert engine.removed == [] and not window.is_busy
    assert len(names_listed(window)) == len(SAMPLE_BOOKS)
    assert all(button.get_sensitive() for button in window._library._delete_buttons)


# -- the file step on its own ----------------------------------------------------------------------

def test_discarding_without_a_trash_deletes_the_file(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("text", encoding="utf-8")
    library_page._discard_file(str(path), trash=False)

    assert not path.exists()


def test_discarding_a_file_that_is_already_gone_is_not_an_error(tmp_path):
    library_page._discard_file(str(tmp_path / "missing.txt"), trash=False)
    library_page._discard_file(str(tmp_path / "missing.txt"), trash=True)


def test_a_file_can_be_trashed_only_where_the_system_allows_it(tmp_path):
    assert library_page._can_trash(str(tmp_path / "missing.txt")) in (True, False)      # Never raises.
    assert library_page._can_trash("/nonexistent-folder/book.txt") is False


def test_the_trash_is_used_when_asked_for(tmp_path, monkeypatch):
    calls = []

    class FakeFile:
        def trash(self, cancellable):
            calls.append("trash")

        def delete(self, cancellable):
            calls.append("delete")

    monkeypatch.setattr(library_page.Gio.File, "new_for_path", staticmethod(lambda _path: FakeFile()))
    library_page._discard_file("/books/a.txt", trash=True)
    library_page._discard_file("/books/a.txt", trash=False)

    assert calls == ["trash", "delete"]
