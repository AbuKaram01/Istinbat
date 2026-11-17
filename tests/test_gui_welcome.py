# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The first-run welcome guide, driven through the real interface with a fake downloader."""

import os

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

from gui_fakes import FakeDownloader
from gui_support import build_app, pump, start

from istinbat.core.catalog import EMBEDDER, LLMS, RERANKER
from istinbat.core.settings import Language, load_settings
from istinbat.gui.model_downloads import RowState
from istinbat.gui.welcome import WelcomeDialog


@pytest.fixture
def downloader():
    fake = FakeDownloader()
    yield fake
    fake.release.set()


@pytest.fixture
def make_app(tmp_path, downloader):
    created = []

    def factory(**options):
        options.setdefault("welcome", True)
        app, services, engine = build_app(tmp_path / f"run{len(created)}", downloader=downloader, **options)
        created.append((app, services))
        return app, services, engine

    yield factory

    for app, services in created:
        services.downloads.cancel()
        services.downloads.join(2)
        for window in list(app.get_windows()):
            window.destroy()
        services.worker.shutdown(timeout=1)
    Gtk.Widget.set_default_direction(Gtk.TextDirection.LTR)


def guide_of(window):
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, WelcomeDialog), f"the visible dialog is {dialog!r}"
    return dialog


def choose_all_models(services, tmp_path):
    for attribute in ("embedder_model", "reranker_model", "llm_model"):
        path = tmp_path / attribute
        path.write_bytes(b"x")
        setattr(services.settings.paths, attribute, str(path))


def labels(dialog):
    return dialog._next.get_label(), dialog._back.get_visible()


def go_to_the_last_page(dialog):
    for _ in range(2):
        dialog._next.emit("clicked")
    pump(0.2)


# -- when the guide opens --------------------------------------------------------------------------

def test_the_guide_opens_by_itself_on_the_first_start_without_models_and_loads_nothing(make_app):
    app, services, engine = make_app()
    window = start(app, services, load=False)
    pump(0.3)

    guide_of(window)
    assert engine.loads == 0 and services.engine is None


def test_the_guide_does_not_open_once_it_has_been_seen(make_app):
    app, services, _ = make_app(welcome=False)
    window = start(app, services, load=False)

    assert window.get_visible_dialog() is None


def test_an_installation_that_already_has_its_models_skips_the_guide_and_is_marked_done(make_app, tmp_path):
    app, services, _ = make_app()
    choose_all_models(services, tmp_path)
    window = start(app, services, load=False)

    assert window.get_visible_dialog() is None and services.settings.app.welcome_done


def test_the_main_menu_reopens_the_guide_whenever_the_user_wants_it(make_app):
    app, services, _ = make_app(welcome=False)
    window = start(app, services, load=False)

    app.activate_action("welcome-guide", None)
    pump(0.3)
    guide_of(window)


def test_closing_the_guide_is_remembered_in_the_settings_file(make_app, tmp_path):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    guide_of(window).close()
    pump(0.5)

    assert load_settings(tmp_path / "run0" / "settings.json").app.welcome_done


# -- the pages -------------------------------------------------------------------------------------

def test_the_guide_walks_through_three_pages_with_back_and_next(make_app):
    app, services, _ = make_app()
    dialog = guide_of(start(app, services, load=False))

    assert labels(dialog) == ("Next", False)                       # The first page has no Back.
    dialog._next.emit("clicked")
    assert dialog._index == 1 and labels(dialog) == ("Next", True)
    dialog._next.emit("clicked")
    assert dialog._index == 2 and labels(dialog) == ("Close", True)
    dialog._back.emit("clicked")
    assert dialog._index == 1


def test_the_models_page_lists_the_same_rows_as_preferences_without_a_menu_around_them(make_app):
    app, services, _ = make_app()
    dialog = guide_of(start(app, services, load=False))
    group = dialog._downloads

    assert group.expander is None and group.get_title() == ""
    assert {EMBEDDER.key, RERANKER.key} <= set(group._rows) and all(option.key in group._rows for option in LLMS)
    assert all(row.state is RowState.DOWNLOAD for row in group._rows.values())
    assert services.settings.paths.models_dir in dialog._note.get_label()


def test_the_last_page_says_which_models_are_missing(make_app):
    app, services, _ = make_app()
    dialog = guide_of(start(app, services, load=False))
    go_to_the_last_page(dialog)

    assert dialog._finish.get_title() == "Almost there"
    text = dialog._finish.get_description()
    assert "an embedding model, a reranking model and a language model" in text


def test_the_last_page_names_only_what_is_still_missing(make_app, tmp_path):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    dialog = guide_of(window)
    path = tmp_path / "embedder"
    path.write_bytes(b"x")
    services.settings.paths.embedder_model = str(path)
    go_to_the_last_page(dialog)

    text = dialog._finish.get_description()
    assert "an embedding model" not in text and "a reranking model and a language model" in text


def test_with_every_model_present_the_last_page_says_all_set_and_offers_to_start(make_app, tmp_path):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    dialog = guide_of(window)
    choose_all_models(services, tmp_path)
    go_to_the_last_page(dialog)

    assert dialog._finish.get_title() == "You’re all set" and labels(dialog)[0] == "Start Asking"
    dialog._next.emit("clicked")                                    # On the last page the button closes the guide.
    pump(0.5)
    assert window.get_visible_dialog() is None


# -- downloading from the guide --------------------------------------------------------------------

def download(window, dialog, key):
    """Press a row's Download button and accept the confirmation, which closes as it does for a real click."""
    dialog._downloads._rows[key]._download.emit("clicked")
    pump(0.2)
    confirmation = window.get_visible_dialog()
    confirmation.emit("response", "confirm")
    confirmation.force_close()
    pump(0.3)


def test_a_download_started_in_the_guide_shows_progress_and_is_selected_when_it_finishes(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    dialog = guide_of(window)
    download(window, dialog, EMBEDDER.key)

    assert dialog._downloads._rows[EMBEDDER.key].state is RowState.DOWNLOADING
    downloader.release.set()
    services.downloads.join(5)
    pump(0.5)

    assert dialog._downloads._rows[EMBEDDER.key].state is RowState.IN_USE
    assert services.settings.paths.embedder_model.endswith(EMBEDDER.directory)


def test_closing_the_guide_does_not_stop_a_download_that_is_running(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    dialog = guide_of(window)
    download(window, dialog, EMBEDDER.key)
    dialog.close()
    pump(0.5)

    assert services.downloads.active
    downloader.release.set()
    services.downloads.join(5)
    pump(0.3)
    assert services.settings.paths.embedder_model.endswith(EMBEDDER.directory)


def test_the_last_page_mentions_a_download_that_carries_on_in_the_background(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    dialog = guide_of(window)
    download(window, dialog, EMBEDDER.key)
    go_to_the_last_page(dialog)

    assert "carries on in the background" in dialog._finish.get_description()


def test_how_a_download_ended_is_shown_inside_the_guide_where_the_user_is_looking(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services, load=False)
    dialog = guide_of(window)
    toasts = []
    dialog.add_toast = toasts.append
    download(window, dialog, EMBEDDER.key)
    downloader.release.set()
    services.downloads.join(5)
    pump(0.5)

    assert [toast.get_title() for toast in toasts] == ["Embedding model downloaded and selected."]


# -- Arabic ----------------------------------------------------------------------------------------

def test_the_guide_is_translated_into_arabic(make_app):
    app, services, _ = make_app()
    services.set_language(Language.AR)
    dialog = guide_of(start(app, services, load=False))

    assert dialog.get_title() == "مرحباً"
    assert dialog._next.get_label() == "التالي"
    go_to_the_last_page(dialog)
    assert dialog._finish.get_title() == "أوشكنا على الانتهاء" and "نموذج التضمين" in dialog._finish.get_description()
