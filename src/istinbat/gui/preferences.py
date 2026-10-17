# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Preferences dialog. Every change is saved immediately; there is no Apply step."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..core.settings import AnswerLanguage, RewriteMode
from ..storage import ExportLabels
from .model_downloads import ModelDownloadGroup

if TYPE_CHECKING:
    from .window import MainWindow

_REWRITE_ORDER = [RewriteMode.ALWAYS, RewriteMode.AUTO, RewriteMode.OFF]
_ANSWER_LANGUAGE_ORDER = [AnswerLanguage.AUTO, AnswerLanguage.ARABIC, AnswerLanguage.ENGLISH]
_AUTO_DELETE_CHOICES = [0, 7, 30, 90]
_CONTEXT_STEP = 500
_SCROLL_MARGIN = 12
_SCROLL_RETRY_MS = 50
_SCROLL_MAX_ATTEMPTS = 40


def _find_scrolled_window(widget: Gtk.Widget) -> Gtk.ScrolledWindow | None:
    """The first scrolled window below ``widget`` (the one that holds the preferences page)."""
    if isinstance(widget, Gtk.ScrolledWindow):
        return widget
    child = widget.get_first_child()
    while child is not None:
        if (found := _find_scrolled_window(child)) is not None:
            return found
        child = child.get_next_sibling()
    return None


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self._window = window
        self._services = window.services
        self._t = window.services.translate
        self._settings = window.services.settings
        self._restart_hint_shown = False
        self._path_rows: dict[str, Adw.EntryRow] = {}
        self._scroll_attempts = 0

        self.set_title(self._t("prefs.title"))
        self.set_search_enabled(False)
        page = Adw.PreferencesPage()
        self.add(page)
        paths = self._paths_group()
        folder = self._path_row(
            self._t("prefs.models.folder"), self._settings.paths, "models_dir", True, False,
            after_save=lambda: self._downloads.refresh(),
        )
        self._downloads = ModelDownloadGroup(self, self._services, folder, self.refresh_model_paths)
        for group in (paths, self._downloads, self._performance_group(), self._general_group(), self._data_group()):
            page.add(group)
        self.connect("closed", lambda _dialog: self._downloads.detach())

    def show_downloads(self) -> None:
        """Open the "Download models" menu and bring it into view (used by the error page shortcut)."""
        self._downloads.expand()
        self._scroll_attempts = 0
        GLib.timeout_add(_SCROLL_RETRY_MS, self._scroll_to_downloads)

    def _scroll_to_downloads(self) -> bool:
        """Scroll once the dialog has been laid out; try again shortly if it has not been yet."""
        self._scroll_attempts += 1
        scrolled = _find_scrolled_window(self)
        if scrolled is not None and scrolled.get_child() is not None:
            adjustment = scrolled.get_vadjustment()
            found, bounds = self._downloads.compute_bounds(scrolled.get_child())
            if found and adjustment.get_upper() > adjustment.get_page_size():
                adjustment.set_value(max(0.0, bounds.get_y() - _SCROLL_MARGIN))
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE if self._scroll_attempts < _SCROLL_MAX_ATTEMPTS else GLib.SOURCE_REMOVE

    def refresh_model_paths(self) -> None:
        """Show the model paths the settings now hold, after a download or "Use"."""
        for attribute in ("llm_model", "embedder_model", "reranker_model"):
            self._path_rows[attribute].set_text(getattr(self._settings.paths, attribute))
        self._show_restart_hint()

    # -- Groups -------------------------------------------------------------------

    def _paths_group(self) -> Adw.PreferencesGroup:
        paths = self._settings.paths
        group = Adw.PreferencesGroup(
            title=self._t("prefs.paths.title"), description=self._t("prefs.paths.description"),
        )
        for key, attribute, pick_folder, needs_reload in (
            ("prefs.paths.books", "books_dir", True, False),
            ("prefs.paths.llm", "llm_model", False, True),
            ("prefs.paths.embedder", "embedder_model", True, True),
            ("prefs.paths.reranker", "reranker_model", True, True),
        ):
            group.add(self._path_row(self._t(key), paths, attribute, pick_folder, needs_reload))

        reload_row = Adw.ActionRow(
            title=self._t("prefs.reload.title"), subtitle=self._t("prefs.reload.subtitle"),
        )
        reload_button = Gtk.Button(label=self._t("prefs.reload.button"), valign=Gtk.Align.CENTER)
        reload_button.connect("clicked", self._on_reload_clicked)
        reload_row.add_suffix(reload_button)
        group.add(reload_row)
        return group

    def _path_row(
        self,
        title: str,
        section: object,
        attribute: str,
        pick_folder: bool,
        needs_reload: bool,
        after_save: Callable[[], None] | None = None,
    ) -> Adw.EntryRow:
        row = Adw.EntryRow(title=title, show_apply_button=True)
        row.set_text(getattr(section, attribute))
        self._path_rows[attribute] = row

        def save(_row: Adw.EntryRow | None = None) -> None:
            setattr(section, attribute, row.get_text().strip())
            self._services.save_settings()
            if needs_reload:
                self._show_restart_hint()
            if after_save is not None:
                after_save()

        row.connect("apply", save)
        browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
        browse.set_tooltip_text(self._t("prefs.browse"))
        browse.connect("clicked", lambda _b: self._browse(pick_folder, row, save))
        row.add_suffix(browse)
        return row

    def _browse(self, pick_folder: bool, row: Adw.EntryRow, save: Callable[[], None]) -> None:
        dialog = Gtk.FileDialog(title=row.get_title())

        def chosen(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                file = source.select_folder_finish(result) if pick_folder else source.open_finish(result)
            except GLib.Error:
                return  # Dismissed.
            if file and file.get_path():
                row.set_text(file.get_path())
                save()

        if pick_folder:
            dialog.select_folder(self._window, None, chosen)
        else:
            dialog.open(self._window, None, chosen)

    def _performance_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=self._t("prefs.performance.title"))
        llm, retrieval, memory = self._settings.llm, self._settings.retrieval, self._settings.memory

        threads = Adw.SpinRow.new_with_range(1, 64, 1)
        threads.set_title(self._t("prefs.threads.title"))
        threads.set_subtitle(self._t("prefs.threads.subtitle"))
        threads.set_value(llm.threads)
        threads.connect("notify::value", lambda row, _p: self._set_threads(int(row.get_value())))
        group.add(threads)

        sources = Adw.SpinRow.new_with_range(1, 10, 1)
        sources.set_title(self._t("prefs.sources.title"))
        sources.set_value(retrieval.top_sources)
        sources.connect(
            "notify::value", lambda row, _p: self._set_value(retrieval, "top_sources", int(row.get_value())),
        )
        group.add(sources)

        context = Adw.SpinRow.new_with_range(500, 12000, _CONTEXT_STEP)
        context.set_title(self._t("prefs.context.title"))
        context.set_subtitle(self._t("prefs.context.subtitle"))
        context.set_value(retrieval.max_context_chars)
        context.connect(
            "notify::value", lambda row, _p: self._set_value(retrieval, "max_context_chars", int(row.get_value())),
        )
        group.add(context)

        rewrite = Adw.ComboRow(title=self._t("prefs.rewrite.title"), subtitle=self._t("prefs.rewrite.subtitle"))
        rewrite.set_model(Gtk.StringList.new([self._t(f"prefs.rewrite.{mode.value}") for mode in _REWRITE_ORDER]))
        rewrite.set_selected(_REWRITE_ORDER.index(memory.rewrite_mode))
        rewrite.connect(
            "notify::selected",
            lambda row, _p: self._set_value(memory, "rewrite_mode", _REWRITE_ORDER[row.get_selected()]),
        )
        group.add(rewrite)

        answer_language = Adw.ComboRow(
            title=self._t("prefs.answer_language.title"), subtitle=self._t("prefs.answer_language.subtitle"),
        )
        answer_language.set_model(Gtk.StringList.new(
            [self._t(f"prefs.answer_language.{choice.value}") for choice in _ANSWER_LANGUAGE_ORDER],
        ))
        answer_language.set_selected(_ANSWER_LANGUAGE_ORDER.index(memory.answer_language))
        answer_language.connect(
            "notify::selected",
            lambda row, _p: self._set_value(memory, "answer_language", _ANSWER_LANGUAGE_ORDER[row.get_selected()]),
        )
        group.add(answer_language)
        return group

    def _general_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=self._t("prefs.general.title"))
        notify = Adw.SwitchRow(
            title=self._t("prefs.notify.title"), subtitle=self._t("prefs.notify.subtitle"),
            active=self._settings.app.notify_on_answer,
        )
        notify.connect(
            "notify::active",
            lambda row, _p: self._set_value(self._settings.app, "notify_on_answer", row.get_active()),
        )
        group.add(notify)

        appearance = Adw.ActionRow(
            title=self._t("prefs.appearance.title"), subtitle=self._t("prefs.appearance.subtitle"),
        )
        group.add(appearance)
        return group

    def _data_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=self._t("prefs.data.title"))
        self._stats_row = Adw.ActionRow(title=self._t("prefs.data.saved"))
        group.add(self._stats_row)
        self._refresh_stats()

        choices = list(_AUTO_DELETE_CHOICES)
        current = self._settings.app.auto_delete_days
        if current not in choices:
            choices.append(current)
        auto_delete = Adw.ComboRow(
            title=self._t("prefs.data.auto_delete.title"), subtitle=self._t("prefs.data.auto_delete.subtitle"),
        )
        auto_delete.set_model(Gtk.StringList.new([self._auto_delete_label(days) for days in choices]))
        auto_delete.set_selected(choices.index(current))
        auto_delete.connect(
            "notify::selected",
            lambda row, _p: self._set_value(self._settings.app, "auto_delete_days", choices[row.get_selected()]),
        )
        group.add(auto_delete)

        group.add(self._action_row("prefs.data.export", "prefs.data.export.button", self._on_export_clicked, False))
        group.add(self._action_row("prefs.data.rebuild", "prefs.data.rebuild.button", self._on_rebuild_clicked, False))
        group.add(self._action_row("prefs.data.delete", "prefs.data.delete.button", self._on_delete_all_clicked, True))
        return group

    def _action_row(self, key: str, button_key: str, callback: Callable[[], None], destructive: bool) -> Adw.ActionRow:
        row = Adw.ActionRow(title=self._t(key), subtitle=self._t(f"{key}.subtitle"))
        button = Gtk.Button(label=self._t(button_key), valign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action" if destructive else "flat")
        button.connect("clicked", lambda _b: callback())
        row.add_suffix(button)
        return row

    # -- Behavior -----------------------------------------------------------------

    def _set_value(self, section: object, attribute: str, value: object) -> None:
        setattr(section, attribute, value)
        self._services.save_settings()

    def _set_threads(self, value: int) -> None:
        self._settings.llm.threads = value
        self._settings.llm.batch_threads = value
        self._services.save_settings()
        self._show_restart_hint()

    def _auto_delete_label(self, days: int) -> str:
        if days == 0:
            return self._t("prefs.data.auto_delete.never")
        return self._t("prefs.data.auto_delete.days", days=days)

    def _show_restart_hint(self) -> None:
        if not self._restart_hint_shown:
            self._restart_hint_shown = True
            self.add_toast(Adw.Toast(title=self._t("prefs.reload.hint")))

    def _refresh_stats(self) -> None:
        stats = self._services.store.stats()
        self._stats_row.set_subtitle(self._t("prefs.data.stats", conversations=stats.conversations, turns=stats.turns))

    def _on_reload_clicked(self, _button: Gtk.Button) -> None:
        self.close()
        self._window.reload_engine()

    def _on_export_clicked(self) -> None:
        conversation_id = self._window.current_conversation_id
        if conversation_id is None:
            self.add_toast(Adw.Toast(title=self._t("prefs.data.export.none")))
            return
        dialog = Gtk.FileDialog(title=self._t("prefs.data.export"), initial_name="conversation.md")

        def chosen(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                file = source.save_finish(result)
            except GLib.Error:
                return
            labels = ExportLabels(**{name: self._t(f"export.{name}") for name in ExportLabels.__dataclass_fields__})
            markdown = self._services.store.export_markdown(conversation_id, labels)
            file.replace_contents(markdown.encode("utf-8"), None, False, Gio.FileCreateFlags.NONE, None)
            self.add_toast(Adw.Toast(title=self._t("prefs.data.export.done")))

        dialog.save(self._window, None, chosen)

    def _on_rebuild_clicked(self) -> None:
        from .widgets import confirm

        confirm(
            self,
            heading=self._t("prefs.data.rebuild.confirm.heading"),
            body=self._t("prefs.data.rebuild.confirm.body"),
            confirm_label=self._t("prefs.data.rebuild.button"), cancel_label=self._t("dialog.cancel"),
            on_confirm=self._rebuild, destructive=False,
        )

    def _rebuild(self) -> None:
        self.close()
        self._window.rebuild_index()

    def _on_delete_all_clicked(self) -> None:
        from .widgets import confirm

        confirm(
            self, heading=self._t("prefs.data.delete.confirm.heading"), body=self._t("prefs.data.delete.confirm.body"),
            confirm_label=self._t("prefs.data.delete.button"), cancel_label=self._t("dialog.cancel"),
            on_confirm=self._delete_all,
        )

    def _delete_all(self) -> None:
        self._services.store.delete_all()
        self._refresh_stats()
        self._window.on_conversations_deleted()
