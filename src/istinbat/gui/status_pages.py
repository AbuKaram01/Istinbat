# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Full-window pages shown before the interface is usable: loading and error."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import APP_ID
from .widgets import window_buttons

_PROGRESS_WIDTH = 320


def _header(translate: Callable[..., str]) -> Adw.HeaderBar:
    header = Adw.HeaderBar()
    header.set_show_title(False)
    language, primary = window_buttons(translate)
    header.pack_end(primary)
    header.pack_end(language)
    return header


class LoadingPage(Adw.Bin):
    """Shown while the models load, with a progress bar."""

    def __init__(self, translate: Callable[..., str]) -> None:
        super().__init__()
        view = Adw.ToolbarView()
        view.add_top_bar(_header(translate))
        self._progress = Gtk.ProgressBar(halign=Gtk.Align.CENTER, width_request=_PROGRESS_WIDTH)
        self._detail = Gtk.Label(css_classes=["dim-label"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._progress)
        box.append(self._detail)
        view.set_content(Adw.StatusPage(icon_name=APP_ID, title=translate("loading.title"), child=box))
        self.set_child(view)

    def set_progress(self, fraction: float, detail: str) -> None:
        self._progress.set_fraction(fraction)
        self._detail.set_label(detail)


class ErrorPage(Adw.Bin):
    """Shown when the models cannot be loaded (typically a first run with no model paths).

    Args:
        translate: The interface translator.
        on_back: Called by the "Back" button, which returns to the conversation with the models still unloaded.
    """

    def __init__(self, translate: Callable[..., str], on_back: Callable[[], None]) -> None:
        super().__init__()
        view = Adw.ToolbarView()
        view.add_top_bar(_header(translate))
        preferences = Gtk.Button(label=translate("error.open_preferences"), halign=Gtk.Align.CENTER)
        preferences.add_css_class("pill")
        preferences.set_action_name("app.preferences")
        download = Gtk.Button(label=translate("error.download_models"), halign=Gtk.Align.CENTER)
        download.add_css_class("suggested-action")
        download.add_css_class("pill")
        download.set_action_name("app.download-models")
        retry = Gtk.Button(label=translate("error.retry"), halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.set_action_name("app.reload-engine")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        back = Gtk.Button(label=translate("error.back"), halign=Gtk.Align.CENTER, css_classes=["flat"])
        back.connect("clicked", lambda _button: on_back())
        box.append(download)
        box.append(preferences)
        box.append(retry)
        box.append(back)
        self._page = Adw.StatusPage(icon_name="dialog-warning-symbolic", title=translate("error.title"), child=box)
        view.set_content(self._page)
        self.set_child(view)

    def set_detail(self, detail: str) -> None:
        self._page.set_description(detail)
