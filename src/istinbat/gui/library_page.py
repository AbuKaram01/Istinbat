# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The library page: books on disk, their index status, and indexing controls."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..core.indexer import BookInfo, BookStatus, IndexReport, scan_library
from ..core.progress import Progress
from ..services import Task
from .widgets import apply_text_direction, confirm

if TYPE_CHECKING:
    from .window import MainWindow

_MAX_CONTENT_WIDTH = 720
_STATUS_STYLE = {
    BookStatus.INDEXED: "success",
    BookStatus.NEW: "accent",
    BookStatus.MODIFIED: "warning",
}


def _isolated(text: str) -> str:
    """Wrap ``text`` in isolates, so a book name in the other script cannot reorder the sentence around it."""
    return f"\u2068{text}\u2069"


def _can_trash(path: str) -> bool:
    """Return whether the system can move ``path`` to the Trash (it cannot on some drives and in some sessions)."""
    attribute = Gio.FILE_ATTRIBUTE_ACCESS_CAN_TRASH
    try:
        info = Gio.File.new_for_path(path).query_info(attribute, Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        return False
    return info.get_attribute_boolean(attribute)


def _discard_file(path: str, trash: bool) -> None:
    """Move a book's file to the Trash, or delete it for good when ``trash`` is False.

    A file that is already gone counts as discarded.
    """
    file = Gio.File.new_for_path(path)
    try:
        file.trash(None) if trash else file.delete(None)
    except GLib.Error as error:
        if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
            raise


class LibraryPage(Adw.NavigationPage):
    def __init__(self, window: MainWindow) -> None:
        self._t = window.services.translate
        super().__init__(title=self._t("library.title"), tag="library")
        self._window = window
        self._services = window.services
        self._task: Task | None = None
        self._delete_buttons: list[Gtk.Button] = []
        self._actions_enabled = True

        self._add_button = Gtk.Button(label=self._t("library.add"))
        self._add_button.connect("clicked", self._on_add_clicked)
        self._index_button = Gtk.Button(label=self._t("library.index"), css_classes=["suggested-action"])
        self._index_button.connect("clicked", lambda _b: self._run(lambda engine: engine.index_library))
        header = Adw.HeaderBar()
        header.pack_end(self._index_button)
        header.pack_end(self._add_button)

        self._banner_title = Gtk.Label(xalign=0, css_classes=["heading"])
        self._banner_bar = Gtk.ProgressBar()
        self._cancel_button = Gtk.Button(label=self._t("library.cancel"), halign=Gtk.Align.END)
        self._cancel_button.connect("clicked", lambda _b: self._task and self._task.cancel())
        self._banner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
        self._banner.add_css_class("card")
        for widget in (self._banner_title, self._banner_bar, self._cancel_button):
            self._banner.append(widget)
        for margin in ("top", "bottom", "start", "end"):
            getattr(self._banner, f"set_margin_{margin}")(0)
        self._banner.set_spacing(10)

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._empty = Adw.StatusPage(
            icon_name="accessories-dictionary-symbolic",
            title=self._t("library.empty.title"),
            description=self._t("library.empty.description"),
        )
        self._stack = Gtk.Stack()
        self._stack.add_named(self._list, "books")
        self._stack.add_named(self._empty, "empty")
        self._folder = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"], wrap=True, selectable=True)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for widget in (self._banner, self._stack, self._folder):
            column.append(widget)
        for margin in ("top", "bottom", "start", "end"):
            getattr(column, f"set_margin_{margin}")(18)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(Adw.Clamp(maximum_size=_MAX_CONTENT_WIDTH, child=column))

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(scroller)
        self.set_child(view)
        self.refresh()

    # -- Listing ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-scan the books folder in the background and redraw the list."""
        settings = self._services.settings
        # Isolate the path (LRI ... PDI) so right-to-left text cannot reorder its slashes.
        isolated_path = f"\u2066{settings.paths.books_dir}\u2069"
        self._folder.set_label(self._t("library.folder", path=isolated_path))

        def job(_task: Task) -> list[BookInfo]:
            return scan_library(settings)

        self._services.worker.submit(job, on_done=self._show_books, on_error=lambda _e: self._show_books([]))

    def _show_books(self, books: list[BookInfo]) -> None:
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)
        self._delete_buttons.clear()
        for book in books:
            self._list.append(self._build_row(book))
        self._stack.set_visible_child_name("books" if books else "empty")

    def _build_row(self, book: BookInfo) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(book.name))
        apply_text_direction(row, book.name)
        row.set_subtitle(self._t("library.characters", count=f"{book.characters:,}"))
        badge = Gtk.Label(label=self._t(f"library.status.{book.status.value}"), valign=Gtk.Align.CENTER)
        badge.add_css_class("status-badge")
        badge.add_css_class(_STATUS_STYLE[book.status])
        row.add_suffix(badge)
        row.add_suffix(self._build_delete_button(book, row))
        return row

    def _build_delete_button(self, book: BookInfo, row: Adw.ActionRow) -> Gtk.Button:
        label = self._t("library.delete.tooltip", name=_isolated(book.name))
        button = Gtk.Button(
            icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text=label,
            css_classes=["flat", "circular"], sensitive=self._actions_enabled,
        )
        button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        button.connect("clicked", lambda _button: self._confirm_deletion(book, row))
        self._delete_buttons.append(button)
        return button

    def set_actions_enabled(self, enabled: bool) -> None:
        """Disable indexing and deleting while another job (such as answering a question) is running."""
        self._actions_enabled = enabled
        self._add_button.set_sensitive(enabled)
        self._index_button.set_sensitive(enabled)
        for button in self._delete_buttons:
            button.set_sensitive(enabled)

    # -- Adding books -------------------------------------------------------------

    def _on_add_clicked(self, _button: Gtk.Button) -> None:
        text_files = Gtk.FileFilter(name=self._t("library.filter_text"))
        text_files.add_suffix("txt")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(text_files)
        dialog = Gtk.FileDialog(title=self._t("library.add_dialog"), filters=filters)
        dialog.open_multiple(self._window, None, self._on_files_chosen)

    def _on_files_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # The user dismissed the dialog.
        folder = self._services.settings.paths.books_dir
        os.makedirs(folder, exist_ok=True)
        copied = 0
        for file in files:
            path = file.get_path()
            if path:
                shutil.copy2(path, os.path.join(folder, os.path.basename(path)))
                copied += 1
        self._window.show_toast(self._t("library.added", count=copied))
        self.refresh()

    # -- Deleting books -----------------------------------------------------------

    def _confirm_deletion(self, book: BookInfo, row: Adw.ActionRow) -> None:
        if self._window.is_busy:
            return
        trash = _can_trash(book.path)
        confirm(
            self._window,
            heading=self._t("library.delete.heading", name=_isolated(book.name)),
            body=self._t("library.delete.body.trash" if trash else "library.delete.body.delete"),
            confirm_label=self._t("library.delete.confirm"),
            cancel_label=self._t("dialog.cancel"),
            on_confirm=lambda: self._delete(book, row, trash),
        )

    def _delete(self, book: BookInfo, row: Adw.ActionRow, trash: bool) -> None:
        """Discard the book's file, then take it out of the index.

        The file goes first: if the second step is interrupted, the book is already missing from the folder and the
        next indexing run removes it from the index by itself.
        """
        if self._window.is_busy:
            return
        self._window.set_busy("deleting")
        row.set_sensitive(False)

        def job(_task: Task) -> None:
            _discard_file(book.path, trash)
            self._services.remove_book(book.path)

        self._services.worker.submit(
            job,
            on_done=lambda _result: self._on_deleted(book),
            on_error=lambda error: self._on_delete_failed(book, error),
        )

    def _on_deleted(self, book: BookInfo) -> None:
        self._window.set_busy(None)
        self._window.show_toast(self._t("library.deleted", name=_isolated(book.name)))
        self._window.on_library_changed()
        self.refresh()

    def _on_delete_failed(self, book: BookInfo, error: Exception) -> None:
        self._window.set_busy(None)
        message = getattr(error, "message", None) or str(error)
        self._window.show_toast(self._t("library.delete_failed", name=_isolated(book.name), message=message))
        self._window.on_library_changed()      # The index may have changed before the failure.
        self.refresh()

    # -- Indexing -----------------------------------------------------------------

    def rebuild(self) -> None:
        """Wipe the index and index every book again (called from Preferences)."""
        self._run(lambda engine: engine.rebuild_index)

    def _run(self, pick) -> None:
        """Index with the engine's ``pick(engine)`` method, loading the models first when that has not happened."""
        if self._window.is_busy:
            return
        self._window.ensure_engine(lambda: self._start(pick(self._services.engine)))

    def _start(self, runner) -> None:
        if self._window.is_busy:
            return
        worker = self._services.worker
        self._window.set_busy("indexing")
        self._banner.set_visible(True)
        self._banner_bar.set_fraction(0.0)
        self._banner_title.set_label(self._t("progress.index.scanning"))

        def job(task: Task) -> IndexReport:
            return runner(progress=lambda p: worker.post(self._on_progress, p), cancel=task.is_cancelled)

        self._task = worker.submit(job, on_done=self._on_finished, on_error=self._on_failed)

    def _on_progress(self, progress: Progress) -> None:
        self._banner_bar.set_fraction(progress.fraction)
        message = self._t(f"progress.{progress.key.value}", **progress.args)
        self._banner_title.set_label(f"{message}  {progress.fraction:.0%}")

    def _on_finished(self, report: IndexReport) -> None:
        self._end_indexing()
        if report.cancelled:
            message = self._t("library.stopped")
        elif report.nothing_to_do:
            message = self._t("progress.index.up_to_date")
        else:
            message = self._t("library.indexed", count=report.new_books + report.modified_books)
        self._window.show_toast(message)
        self._window.on_library_changed()
        self.refresh()

    def _on_failed(self, error: Exception) -> None:
        self._end_indexing()
        self._window.show_toast(self._t("library.failed", message=str(error)))

    def _end_indexing(self) -> None:
        self._banner.set_visible(False)
        self._task = None
        self._window.set_busy(None)
