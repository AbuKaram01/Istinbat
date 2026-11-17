# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The "Download models" menu in Preferences, driven through the real interface with a fake downloader."""

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

from gui_fakes import FakeDownloader
from gui_support import build_app, pump, start

from istinbat.core.catalog import EMBEDDER, LLMS, RERANKER, option_by_key
from istinbat.core.downloads import NotEnoughSpaceError
from istinbat.core.settings import Language
from istinbat.gui.formatting import size_label
from istinbat.gui.model_downloads import RowState
from istinbat.gui.preferences import PreferencesDialog


@pytest.fixture
def downloader():
    fake = FakeDownloader()
    yield fake
    fake.release.set()


@pytest.fixture
def make_app(tmp_path, downloader):
    created = []

    def factory(**options):
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


def open_preferences(window):
    dialog = PreferencesDialog(window)
    dialog.present(window)
    pump(0.2)
    return dialog


def download(window, dialog, key):
    """Press a row's Download button and accept the confirmation."""
    dialog._downloads._rows[key]._download.emit("clicked")
    pump(0.2)
    window.get_visible_dialog().emit("response", "confirm")
    pump(0.2)


def states(dialog):
    return {key: row.state for key, row in dialog._downloads._rows.items()}


# -- the menu --------------------------------------------------------------------------------------

def test_the_menu_is_collapsed_and_offers_the_embedder_the_reranker_and_all_six_language_models(make_app):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)

    group = dialog._downloads
    assert not group.expander.get_expanded()
    assert list(group._rows) == [
        "embedder", "reranker",
        "llm.e2b.q4_k_xl", "llm.e2b.q6_k_xl", "llm.e2b.q8_k_xl",
        "llm.e4b.q4_k_xl", "llm.e4b.q6_k_xl", "llm.e4b.q8_k_xl",
    ]
    assert group._rows["embedder"].get_title() == "Embedding model"
    assert "BAAI/bge-m3" in group._rows["embedder"].get_subtitle()
    assert "bge-reranker-v2-m3" in group._rows["reranker"].get_subtitle()
    assert [group._rows[o.key].get_title() for o in LLMS[:3]] == ["Q4_K_XL", "Q6_K_XL", "Q8_K_XL"]
    assert size_label(LLMS[0].approx_bytes) in group._rows[LLMS[0].key].get_subtitle()
    assert all(state is RowState.DOWNLOAD for state in states(dialog).values())


def test_the_error_page_shortcut_opens_the_menu_expanded(make_app):
    app, services, _ = make_app(fail_load=True)
    window = start(app, services)
    dialog = PreferencesDialog(window)
    dialog.show_downloads()
    dialog.present(window)
    pump(0.2)
    assert dialog._downloads.expander.get_expanded()


def test_the_download_models_action_opens_preferences_with_the_menu_open(make_app):
    app, services, _ = make_app(fail_load=True)
    window = start(app, services)
    assert window._stack.get_visible_child_name() == "error"

    app.activate_action("download-models", None)
    pump(0.3)
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, PreferencesDialog) and dialog._downloads.expander.get_expanded()


def test_the_error_page_offers_the_download_shortcut(make_app):
    app, services, _ = make_app(fail_load=True)
    window = start(app, services)

    def buttons(widget):
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                yield child
            yield from buttons(child)
            child = child.get_next_sibling()

    actions = {button.get_action_name() for button in buttons(window._error)}
    assert "app.download-models" in actions


def test_the_downloads_folder_is_a_setting_and_defaults_to_the_models_folder(make_app, tmp_path):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    assert dialog._path_rows["models_dir"].get_text() == str(tmp_path / "run0" / "models")


# -- downloading -------------------------------------------------------------------------------------

def test_pressing_download_asks_first_and_nothing_starts_until_it_is_confirmed(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)

    dialog._downloads._rows["llm.e2b.q4_k_xl"]._download.emit("clicked")
    pump(0.2)
    alert = window.get_visible_dialog()
    assert "Gemma E2B Q4_K_XL" in alert.get_heading() and "unsloth/gemma-4-E2B-it-GGUF" in alert.get_body()
    assert downloader.calls == [] and not services.downloads.active

    alert.emit("response", "cancel")
    pump(0.2)
    assert downloader.calls == []


def test_a_confirmed_download_shows_progress_and_locks_the_other_download_buttons(make_app, downloader, tmp_path):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    download(window, dialog, "llm.e4b.q6_k_xl")

    pump(2, until=lambda: dialog._downloads._rows["llm.e4b.q6_k_xl"].state is RowState.DOWNLOADING
         and services.downloads.progress is not None)
    row = dialog._downloads._rows["llm.e4b.q6_k_xl"]
    assert downloader.calls == [("llm.e4b.q6_k_xl", str(tmp_path / "run0" / "models"))]
    assert row.state is RowState.DOWNLOADING and "of" in row.get_subtitle() and "GB" in row.get_subtitle()
    others = [r for key, r in dialog._downloads._rows.items() if key != "llm.e4b.q6_k_xl"]
    assert all(not r._download.get_sensitive() for r in others)


def test_a_finished_download_is_selected_marked_in_use_and_reflected_in_the_path_field(make_app, downloader, tmp_path):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    download(window, dialog, "reranker")
    downloader.release.set()
    pump(3, until=lambda: dialog._downloads._rows["reranker"].state is RowState.IN_USE)

    expected = str(tmp_path / "run0" / "models" / "bge-reranker-v2-m3")
    assert services.settings.paths.reranker_model == expected
    assert dialog._path_rows["reranker_model"].get_text() == expected
    assert not services.downloads.active
    assert dialog._downloads._rows["embedder"]._download.get_sensitive()          # Unlocked again.


def test_stopping_a_download_returns_the_row_to_download_and_keeps_the_settings_untouched(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    download(window, dialog, "embedder")
    pump(2, until=lambda: services.downloads.progress is not None)

    services.downloads.cancel()
    pump(3, until=lambda: not services.downloads.active)
    pump(0.2)
    assert dialog._downloads._rows["embedder"].state is RowState.DOWNLOAD
    assert services.settings.paths.embedder_model == ""


def test_a_failed_download_returns_the_row_to_download(make_app, downloader):
    downloader.failure = OSError("boom")
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    download(window, dialog, "embedder")
    downloader.release.set()
    pump(3, until=lambda: not services.downloads.active)
    pump(0.2)
    assert dialog._downloads._rows["embedder"].state is RowState.DOWNLOAD


def test_the_window_reports_how_a_download_ended_even_when_preferences_is_closed(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services)
    toasts = []
    window._toasts.add_toast = toasts.append
    dialog = open_preferences(window)
    download(window, dialog, "reranker")
    dialog.close()
    pump(0.2)
    downloader.release.set()
    pump(3, until=lambda: not services.downloads.active)
    pump(0.2)

    assert [t.get_title() for t in toasts] == ["Reranking model downloaded and selected."]
    assert toasts[0].get_button_label() == "Reload models"


def test_a_full_disk_is_explained_in_the_window(make_app, downloader):
    downloader.failure = NotEnoughSpaceError(5_000_000_000, 1_000_000_000)
    app, services, _ = make_app()
    window = start(app, services)
    toasts = []
    window._toasts.add_toast = toasts.append
    dialog = open_preferences(window)
    download(window, dialog, "embedder")
    dialog.close()
    downloader.release.set()
    pump(3, until=lambda: not services.downloads.active)
    pump(0.2)
    assert toasts and "5.0 GB needed, 1.0 GB available" in toasts[0].get_title()


def test_reopening_preferences_shows_the_download_that_is_still_running(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    download(window, dialog, "llm.e2b.q8_k_xl")
    pump(2, until=lambda: services.downloads.progress is not None)
    dialog.close()
    pump(0.2)

    again = open_preferences(window)
    assert again._downloads._rows["llm.e2b.q8_k_xl"].state is RowState.DOWNLOADING


def test_closing_the_window_during_a_download_asks_for_confirmation(make_app, downloader):
    app, services, _ = make_app()
    window = start(app, services)
    dialog = open_preferences(window)
    download(window, dialog, "embedder")
    dialog.close()
    pump(0.2)

    assert window._on_close_request() is True                       # Blocked until the user confirms.
    pump(0.2)
    assert window.get_visible_dialog() is not None


# -- models that are already on disk ------------------------------------------------------------------

def test_a_model_found_on_disk_offers_use_and_switching_changes_the_selection(make_app, tmp_path):
    app, services, _ = make_app()
    models = Path(services.settings.paths.models_dir)
    for option in (option_by_key("llm.e2b.q4_k_xl"), option_by_key("llm.e2b.q6_k_xl")):
        (models / option.directory).mkdir(parents=True, exist_ok=True)
        (models / option.directory / option.entry).write_bytes(b"x")
    services.use_model(option_by_key("llm.e2b.q4_k_xl"))

    window = start(app, services)
    dialog = open_preferences(window)
    assert states(dialog)["llm.e2b.q4_k_xl"] is RowState.IN_USE
    assert states(dialog)["llm.e2b.q6_k_xl"] is RowState.READY
    assert states(dialog)["llm.e2b.q8_k_xl"] is RowState.DOWNLOAD

    dialog._downloads._use(option_by_key("llm.e2b.q6_k_xl"))
    pump(0.2)
    assert states(dialog)["llm.e2b.q6_k_xl"] is RowState.IN_USE and states(dialog)["llm.e2b.q4_k_xl"] is RowState.READY
    assert services.settings.paths.llm_model.endswith("gemma-4-E2B-it-UD-Q6_K_XL.gguf")
    assert dialog._path_rows["llm_model"].get_text() == services.settings.paths.llm_model


def test_an_incomplete_download_is_not_offered_as_ready(make_app):
    app, services, _ = make_app()
    folder = Path(services.settings.paths.models_dir) / EMBEDDER.directory
    folder.mkdir(parents=True)
    (folder / "pytorch_model.bin.part").write_bytes(b"half")
    window = start(app, services)
    assert states(open_preferences(window))["embedder"] is RowState.DOWNLOAD


# -- Arabic ---------------------------------------------------------------------------------------------

def test_the_menu_is_translated_into_arabic(make_app):
    app, services, _ = make_app()
    services.set_language(Language.AR)
    window = start(app, services)
    dialog = open_preferences(window)
    row = dialog._downloads._rows[RERANKER.key]
    assert row.get_title() == "نموذج إعادة الترتيب" and dialog._downloads.get_title() == "تنزيل النماذج"
    assert "الأصغر" in dialog._downloads._rows[LLMS[0].key].get_subtitle()
