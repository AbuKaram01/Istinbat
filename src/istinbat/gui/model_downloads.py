# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The "Download models" section of Preferences: an expandable menu of models to fetch.

    Download models  ▾
      Download folder
      Embedding model        BAAI/bge-m3
      Reranking model        BAAI/bge-reranker-v2-m3
      Language model  ▾
        Gemma E2B  ▾     Q4_K_XL · Q6_K_XL · Q8_K_XL
        Gemma E4B  ▾     Q4_K_XL · Q6_K_XL · Q8_K_XL

Each model row shows what it can do right now: download, show progress with a stop button,
be selected, or say that it is the model in use. The downloads themselves are owned by
``DownloadManager``; this module only reflects its state, so closing and reopening the
dialog while a model downloads shows the same progress.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..core.catalog import EMBEDDER, LLM_FAMILIES, RERANKER, ModelKind, ModelOption, llms_of
from ..core.downloads import DownloadProgress
from ..services import DownloadBusyError, DownloadEvent, DownloadEventKind
from .formatting import size_label
from .widgets import confirm

if TYPE_CHECKING:
    from ..services import AppServices

_PROGRESS_WIDTH = 110


class RowState(str, Enum):
    DOWNLOAD = "download"
    DOWNLOADING = "downloading"
    READY = "ready"        # Downloaded, not selected.
    IN_USE = "in-use"      # Downloaded and selected.


def model_name(option: ModelOption, translate: Callable[..., str]) -> str:
    """A human name such as "Embedding model" or "Gemma E2B Q4_K_XL"."""
    if option.kind is ModelKind.LLM:
        return f"{translate(f'prefs.models.family.{option.family.lower()}')} {option.quant}"
    return translate(f"prefs.models.{option.kind.value}.title")


class ModelRow(Adw.ActionRow):
    """One downloadable model with a button that changes with its state."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        translate: Callable[..., str],
        *,
        on_download: Callable[[], None],
        on_stop: Callable[[], None],
        on_use: Callable[[], None],
    ) -> None:
        super().__init__(title=title, subtitle=subtitle)
        self._t = translate
        self._base_subtitle = subtitle

        self._download = Gtk.Button(label=translate("prefs.models.download"), valign=Gtk.Align.CENTER)
        self._download.connect("clicked", lambda _b: on_download())

        self._bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=_PROGRESS_WIDTH)
        stop = Gtk.Button(icon_name="process-stop-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
        stop.set_tooltip_text(translate("prefs.models.stop"))
        stop.update_property([Gtk.AccessibleProperty.LABEL], [translate("prefs.models.stop")])
        stop.connect("clicked", lambda _b: on_stop())
        progress = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        progress.append(self._bar)
        progress.append(stop)

        use = Gtk.Button(label=translate("prefs.models.use"), valign=Gtk.Align.CENTER, css_classes=["flat"])
        use.connect("clicked", lambda _b: on_use())

        in_use = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        in_use.append(Gtk.Image(icon_name="object-select-symbolic"))
        in_use.append(Gtk.Label(label=translate("prefs.models.in_use"), css_classes=["dim-label"]))

        self._stack = Gtk.Stack(valign=Gtk.Align.CENTER, hhomogeneous=False)
        for state, widget in (
            (RowState.DOWNLOAD, self._download),
            (RowState.DOWNLOADING, progress),
            (RowState.READY, use),
            (RowState.IN_USE, in_use),
        ):
            self._stack.add_named(widget, state.value)
        self.add_suffix(self._stack)
        self.state = RowState.DOWNLOAD

    def set_state(self, state: RowState, progress: DownloadProgress | None = None) -> None:
        self.state = state
        self._stack.set_visible_child_name(state.value)
        if state is RowState.DOWNLOADING and progress is not None:
            self._bar.set_fraction(progress.fraction)
            self.set_subtitle(self._t(
                "prefs.models.progress", done=size_label(progress.done_bytes), total=size_label(progress.total_bytes),
            ))
        else:
            self._bar.set_fraction(0.0)
            self.set_subtitle(self._base_subtitle)

    def set_download_enabled(self, enabled: bool) -> None:
        self._download.set_sensitive(enabled)


class ModelDownloadGroup(Adw.PreferencesGroup):
    def __init__(
        self,
        parent: Gtk.Widget,
        services: AppServices,
        folder_row: Adw.PreferencesRow,
        on_model_selected: Callable[[], None],
    ) -> None:
        self._t = services.translate
        super().__init__(title=self._t("prefs.models.title"), description=self._t("prefs.models.description"))
        self._parent = parent
        self._services = services
        self._on_model_selected = on_model_selected
        self._rows: dict[str, ModelRow] = {}
        self._options: dict[str, ModelOption] = {}
        self._nested: list[Adw.ExpanderRow] = []      # The language-model expanders, opened by ``expand(True)``.

        self.expander = Adw.ExpanderRow(
            title=self._t("prefs.models.available.title"), subtitle=self._t("prefs.models.available.subtitle"),
            icon_name="folder-download-symbolic",
        )
        self.add(self.expander)
        self.expander.add_row(folder_row)
        self.expander.add_row(self._row(EMBEDDER))
        self.expander.add_row(self._row(RERANKER))
        self.expander.add_row(self._language_models())

        self.refresh()
        services.downloads.subscribe(self._on_event)

    # -- Construction -------------------------------------------------------------------

    def _row(self, option: ModelOption, title: str | None = None, subtitle: str | None = None) -> ModelRow:
        size = size_label(option.approx_bytes)
        if option.kind is ModelKind.LLM:
            subtitle = subtitle or self._t(f"prefs.models.quant.{option.quant.lower()}", size=size)
        else:
            subtitle = self._t(f"prefs.models.{option.kind.value}.subtitle", size=size)
        row = ModelRow(
            title or self._t(f"prefs.models.{option.kind.value}.title"), subtitle, self._t,
            on_download=lambda: self._ask_to_download(option),
            on_stop=self._services.downloads.cancel,
            on_use=lambda: self._use(option),
        )
        self._rows[option.key] = row
        self._options[option.key] = option
        return row

    def _language_models(self) -> Adw.ExpanderRow:
        models = Adw.ExpanderRow(
            title=self._t("prefs.models.llm.title"), subtitle=self._t("prefs.models.llm.subtitle"),
        )
        self._nested.append(models)
        for family in LLM_FAMILIES:
            options = llms_of(family)
            sizes = [option.approx_bytes for option in options]
            expander = Adw.ExpanderRow(
                title=self._t(f"prefs.models.family.{family.lower()}"),
                subtitle=self._t(
                    "prefs.models.family.subtitle", low=size_label(min(sizes)), high=size_label(max(sizes)),
                ),
            )
            for option in options:
                expander.add_row(self._row(option, title=option.quant))
            models.add_row(expander)
            self._nested.append(expander)
        return models

    # -- State --------------------------------------------------------------------------

    def refresh(self) -> None:
        """Show every row in the state that matches the disk, the settings and the running download."""
        manager = self._services.downloads
        paths = self._services.settings.paths
        for key, row in self._rows.items():
            option = self._options[key]
            if manager.current is option:
                row.set_state(RowState.DOWNLOADING, manager.progress)
            elif option.is_downloaded(paths.models_dir):
                chosen = getattr(paths, option.kind.settings_attribute)
                in_use = bool(chosen) and Path(chosen) == option.local_path(paths.models_dir)
                row.set_state(RowState.IN_USE if in_use else RowState.READY)
            else:
                row.set_state(RowState.DOWNLOAD)
                row.set_download_enabled(not manager.active)

    def expand(self, everything: bool = False) -> None:
        """Open the menu; with ``everything`` also the language-model lists inside it."""
        self.expander.set_expanded(True)
        if everything:
            for expander in self._nested:
                expander.set_expanded(True)

    def detach(self) -> None:
        """Stop listening; called when the dialog closes."""
        self._services.downloads.unsubscribe(self._on_event)

    def _on_event(self, event: DownloadEvent) -> None:
        if event.kind is DownloadEventKind.PROGRESS:
            self._rows[event.option.key].set_state(RowState.DOWNLOADING, event.progress)
        else:
            self.refresh()
            if event.kind is DownloadEventKind.FINISHED:
                self._on_model_selected()      # The finished model was selected in the settings.

    # -- Actions ------------------------------------------------------------------------

    def _ask_to_download(self, option: ModelOption) -> None:
        confirm(
            self._parent,
            heading=self._t("prefs.models.confirm.heading", name=model_name(option, self._t)),
            body=self._t(
                "prefs.models.confirm.body", size=size_label(option.approx_bytes), repo=option.repo,
            ),
            confirm_label=self._t("prefs.models.download"), cancel_label=self._t("dialog.cancel"),
            on_confirm=lambda: self._start(option), destructive=False,
        )

    def _start(self, option: ModelOption) -> None:
        try:
            self._services.downloads.start(option)
        except DownloadBusyError:
            self._parent.add_toast(Adw.Toast(title=self._t("prefs.models.busy")))

    def _use(self, option: ModelOption) -> None:
        self._services.use_model(option)
        self.refresh()
        self._on_model_selected()
