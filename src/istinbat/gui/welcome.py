# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The first-run welcome guide: what Istinbat does, then getting the models it needs.

The guide has three pages::

    1. Welcome        what the app does, in three lines
    2. Models         the same download rows as Preferences, with progress and stop
    3. Finish         what is ready and what is still missing

It opens by itself the first time Istinbat starts without models, and from the main menu ("Welcome Guide")
whenever the user wants it again. Downloads belong to the application's ``DownloadManager``, so pressing Close
while a model downloads does not interrupt it.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import APP_ID
from ..core.catalog import ModelKind
from .model_downloads import ModelDownloadGroup

if TYPE_CHECKING:
    from .window import MainWindow

# Positions of the pages in the carousel.
_PAGE_WELCOME, _PAGE_MODELS, _PAGE_FINISH = 0, 1, 2

_DIALOG_WIDTH = 520
_DIALOG_HEIGHT = 700
_COLUMN_WIDTH = 460
_COLUMN_THRESHOLD = 360
_MARGIN = 12
_NEXT_WIDTH = 180

# The rows of the welcome page: icon name, title key and description key.
_FEATURES = (
    ("accessories-dictionary-symbolic", "welcome.feature.books.title", "welcome.feature.books.description"),
    ("system-search-symbolic", "welcome.feature.ask.title", "welcome.feature.ask.description"),
    ("security-high-symbolic", "welcome.feature.private.title", "welcome.feature.private.description"),
)

# What each missing model is called on the last page, by kind.
_MISSING_NAMES = {
    ModelKind.EMBEDDER: "welcome.missing.embedder",
    ModelKind.RERANKER: "welcome.missing.reranker",
    ModelKind.LLM: "welcome.missing.llm",
}


def _scrolled(content: Gtk.Widget) -> Gtk.ScrolledWindow:
    """Wrap ``content`` as a page body: centred, in a comfortable column, scrolling when the dialog is short."""
    clamp = Adw.Clamp(
        maximum_size=_COLUMN_WIDTH, tightening_threshold=_COLUMN_THRESHOLD, margin_start=_MARGIN, margin_end=_MARGIN,
    )
    clamp.set_child(content)
    # hexpand is needed because a carousel gives a page only its natural width unless the page asks for all of it.
    return Gtk.ScrolledWindow(
        child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True, vexpand=True,
    )


class WelcomeDialog(Adw.Dialog):
    """The welcome guide: an introduction, the model download rows and a summary of what is ready.

    Args:
        window: The main window, which owns the shared services and the downloads.
    """

    def __init__(self, window: MainWindow) -> None:
        self._services = window.services
        self._t: Callable[..., str] = window.services.translate
        super().__init__(title=self._t("welcome.title"), content_width=_DIALOG_WIDTH, content_height=_DIALOG_HEIGHT)
        self._index = _PAGE_WELCOME

        self._carousel = Adw.Carousel(
            interactive=False, allow_scroll_wheel=False, allow_mouse_drag=False, allow_long_swipes=False, vexpand=True,
        )
        self._downloads = ModelDownloadGroup(self, self._services, None, self._on_models_changed, flat=True)
        self._downloads.expand_language_models()
        self._pages = [self._welcome_page(), self._models_page(), self._finish_page()]
        for page in self._pages:
            self._carousel.append(page)

        toolbar = Adw.ToolbarView(content=self._build_body())
        toolbar.add_top_bar(Adw.HeaderBar(show_title=False))
        toolbar.set_top_bar_style(Adw.ToolbarStyle.FLAT)
        self.set_child(toolbar)
        self.set_default_widget(self._next)

        self._refresh_note()
        self._update_finish_page()
        self._sync_buttons()
        self._services.downloads.subscribe(self._on_download_event)
        self.connect("closed", self._on_closed)

    # --- Building ---

    def _build_body(self) -> Gtk.Box:
        # The toasts sit on the pages, so they never cover the Back / Next buttons.
        self._toasts = Adw.ToastOverlay(child=self._carousel, vexpand=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self._toasts)
        body.append(Adw.CarouselIndicatorDots(carousel=self._carousel, margin_top=6, margin_bottom=6))
        body.append(self._build_buttons())
        return body

    def _build_buttons(self) -> Gtk.Box:
        self._back = Gtk.Button(label=self._t("welcome.back"), css_classes=["flat", "pill"])
        self._back.connect("clicked", lambda _button: self._go(self._index - 1))
        self._next = Gtk.Button(
            label=self._t("welcome.next"), css_classes=["suggested-action", "pill"], width_request=_NEXT_WIDTH,
        )
        self._next.connect("clicked", self._on_next)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=24)
        buttons.append(self._back)
        buttons.append(self._next)
        return buttons

    # --- Pages ---

    def _welcome_page(self) -> Gtk.Widget:
        features = Adw.PreferencesGroup(margin_top=6, margin_bottom=12)
        for icon_name, title_key, description_key in _FEATURES:
            row = Adw.ActionRow(
                title=self._t(title_key), subtitle=self._t(description_key), subtitle_lines=0, activatable=False,
            )
            row.add_prefix(Gtk.Image(icon_name=icon_name, icon_size=Gtk.IconSize.LARGE))
            features.add(row)
        page = Adw.StatusPage(
            icon_name=APP_ID, title=self._t("welcome.heading"), description=self._t("welcome.tagline"),
            child=features,
        )
        return _scrolled(page)

    def _models_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=12, margin_bottom=12)
        box.append(Gtk.Label(label=self._t("welcome.models.title"), css_classes=["title-1"], wrap=True))
        box.append(Gtk.Label(
            label=self._t("welcome.models.description"),
            wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"],
        ))
        box.append(self._downloads)
        self._note = Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"])
        box.append(self._note)
        return _scrolled(box)

    def _finish_page(self) -> Gtk.Widget:
        self._finish = Adw.StatusPage(icon_name="object-select-symbolic", title="", description="")
        return _scrolled(self._finish)

    # --- State ---

    def _on_download_event(self, _event: object) -> None:
        self._update_finish_page()
        self._sync_buttons()

    def _on_models_changed(self) -> None:
        self._update_finish_page()
        self._sync_buttons()

    def _refresh_note(self) -> None:
        self._note.set_label(self._t("welcome.models.note", folder=self._services.settings.paths.models_dir))

    def _update_finish_page(self) -> None:
        if self._services.settings.paths.models_ready():
            icon, title, text = "object-select-symbolic", self._t("welcome.done.title"), self._t("welcome.done.text")
        else:
            icon, title, text = "folder-download-symbolic", self._t("welcome.almost.title"), self._missing_text()
        self._finish.set_icon_name(icon)
        self._finish.set_title(title)
        self._finish.set_description(text)

    def _missing_text(self) -> str:
        """Say which models are still needed, and that a running download carries on in the background."""
        names = [self._t(_MISSING_NAMES[kind]) for kind in self._missing_kinds()]
        text = self._t("welcome.almost.text", missing=self._list_of(names))
        if self._services.downloads.active:
            text += " " + self._t("welcome.almost.downloading")
        return text

    def _list_of(self, names: list[str]) -> str:
        """Join ``names`` the way the language does it: "a", "a and b", "a, b and c"."""
        if len(names) < 2:
            return "".join(names)
        rest = self._t("welcome.missing.separator").join(names[:-1])
        return self._t("welcome.missing.list", rest=rest, last=names[-1])

    def _missing_kinds(self) -> list[ModelKind]:
        """The kinds of model that are not chosen yet, or whose chosen files have gone."""
        paths = self._services.settings.paths
        missing = []
        for kind in ModelKind:
            chosen = getattr(paths, kind.settings_attribute)
            if not (chosen and os.path.exists(chosen)):
                missing.append(kind)
        return missing

    # --- Navigation ---

    def _go(self, index: int) -> None:
        self._index = max(_PAGE_WELCOME, min(index, _PAGE_FINISH))
        self._carousel.scroll_to(self._pages[self._index], True)
        if self._index == _PAGE_MODELS:
            self._downloads.refresh()
            self._refresh_note()
        if self._index == _PAGE_FINISH:
            self._update_finish_page()
        self._sync_buttons()

    def _on_next(self, _button: Gtk.Button) -> None:
        if self._index == _PAGE_FINISH:
            self.close()
        else:
            self._go(self._index + 1)

    def _sync_buttons(self) -> None:
        self._back.set_visible(self._index > _PAGE_WELCOME)
        if self._index == _PAGE_FINISH:
            ready = self._services.settings.paths.models_ready()
            self._next.set_label(self._t("welcome.start" if ready else "welcome.close"))
        else:
            self._next.set_label(self._t("welcome.next"))

    # --- Shared with the rest of the application ---

    def add_toast(self, toast: Adw.Toast) -> None:
        """Show a toast inside the guide, where the user is looking."""
        self._toasts.add_toast(toast)

    def _on_closed(self, _dialog: Adw.Dialog) -> None:
        self._downloads.detach()
        self._services.downloads.unsubscribe(self._on_download_event)
        self._services.mark_welcome_done()
