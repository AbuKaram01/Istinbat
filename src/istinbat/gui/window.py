# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The main window: loading and error states, conversation sidebar, chat and library pages."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from .. import winsupport
from ..core.downloads import NotEnoughSpaceError
from ..core.progress import Progress
from ..services import AppServices, DownloadEvent, DownloadEventKind
from .chat_view import ChatView
from .formatting import size_label
from .library_page import LibraryPage
from .model_downloads import model_name
from .sidebar import Sidebar
from .status_pages import ErrorPage, LoadingPage
from .widgets import confirm, window_buttons

_DEFAULT_SIZE = (1000, 640)
_MINIMUM_SIZE = (360, 480)
_COLLAPSE_CONDITION = "max-width: 640sp"
_PAGE_LOADING, _PAGE_ERROR, _PAGE_MAIN = "loading", "error", "main"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, services: AppServices) -> None:
        super().__init__(application=application)
        self.services = services
        self._t = services.translate
        self._busy: str | None = None
        self._after_load: Callable[[], None] | None = None    # What to do once the models have loaded.

        self.set_title("Istinbat")
        self.set_default_size(*_DEFAULT_SIZE)
        self.set_size_request(*_MINIMUM_SIZE)
        self.connect("map", lambda *_: winsupport.apply_icon_to_own_windows())    # No-op outside Windows.

        self._toasts = Adw.ToastOverlay()
        self.set_content(self._toasts)
        self._stack = Gtk.Stack()
        self._toasts.set_child(self._stack)

        self._loading = LoadingPage(self._t)
        self._error = ErrorPage(self._t, on_back=self.leave_error)
        self._stack.add_named(self._loading, _PAGE_LOADING)
        self._stack.add_named(self._error, _PAGE_ERROR)
        self._stack.add_named(self._build_main(), _PAGE_MAIN)

        self.connect("close-request", self._on_close_request)
        services.downloads.subscribe(self._on_download_event)
        self.connect("destroy", lambda _window: services.downloads.unsubscribe(self._on_download_event))
        self._show_initial_page()

    # -- Construction -------------------------------------------------------------

    def _build_main(self) -> Adw.NavigationSplitView:
        self._split = Adw.NavigationSplitView()
        self._sidebar = Sidebar(
            self._t,
            on_select=self._on_select_conversation,
            on_delete=self._on_delete_conversation,
            on_new=self.new_conversation,
            on_library=self.open_library,
            on_preferences=lambda: self.get_application().activate_action("preferences", None),
        )
        self._split.set_sidebar(self._sidebar)

        self._chat = ChatView(self)
        self._library = LibraryPage(self)
        self._title = Adw.WindowTitle(title=self._t("chat.new_title"), subtitle="")

        header = Adw.HeaderBar()
        header.set_title_widget(self._title)
        language, primary = window_buttons(self._t)
        header.pack_end(primary)
        header.pack_end(language)
        header.pack_end(self._chat.scope_button)
        chat_view = Adw.ToolbarView()
        chat_view.add_top_bar(header)
        chat_view.set_content(self._chat)

        self._navigation = Adw.NavigationView()
        self._navigation.add(Adw.NavigationPage(title="Istinbat", tag="chat", child=chat_view))
        self._split.set_content(Adw.NavigationPage(title="Istinbat", tag="content", child=self._navigation))

        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(_COLLAPSE_CONDITION))
        breakpoint_.add_setter(self._split, "collapsed", True)
        self.add_breakpoint(breakpoint_)
        return self._split

    def _show_initial_page(self) -> None:
        """Open on the main page: the models are loaded when they are first needed, not when the window opens."""
        if self.services.engine is None and self.services.loading:
            self.show_loading()
        elif self.services.engine is None and self.services.load_error is not None:
            self.on_load_error(self.services.load_error)
        else:
            self._enter_main()

    # -- Engine loading -----------------------------------------------------------

    def ensure_engine(self, on_ready: Callable[[], None]) -> None:
        """Run ``on_ready`` once the engine is loaded, loading the models first if they are not.

        Loading takes a while, so the window shows the loading page meanwhile and carries on afterwards.
        """
        if self.services.engine is not None:
            on_ready()
            return
        self._after_load = on_ready
        if not self.services.loading:
            self.show_loading()
            self.get_application().activate_action("load-engine", None)

    def show_loading(self) -> None:
        self._loading.set_progress(0.0, "")
        self._stack.set_visible_child_name(_PAGE_LOADING)

    def on_load_progress(self, progress: Progress) -> None:
        self._loading.set_progress(progress.fraction, self._t(f"progress.{progress.key.value}"))

    def on_load_done(self) -> None:
        self._enter_main()
        callback, self._after_load = self._after_load, None
        if callback is not None:
            callback()

    def on_load_error(self, error: Exception) -> None:
        self._after_load = None
        self._error.set_detail(str(error))
        self._stack.set_visible_child_name(_PAGE_ERROR)

    def leave_error(self) -> None:
        """Go back to the conversation from the error page (the models stay unloaded)."""
        self.services.clear_load_error()
        self._enter_main()

    def _enter_main(self) -> None:
        self._stack.set_visible_child_name(_PAGE_MAIN)
        self._chat.refresh_books()
        self.refresh_sidebar()

    def reload_engine(self) -> None:
        self.get_application().activate_action("reload-engine", None)

    # -- Conversations ------------------------------------------------------------

    @property
    def current_conversation_id(self) -> int | None:
        return self._chat.conversation_id

    def refresh_sidebar(self, select_id: int | None = None) -> None:
        selected = select_id if select_id is not None else self._chat.conversation_id
        self._sidebar.set_conversations(self.services.store.list_conversations(), selected)

    def new_conversation(self) -> None:
        self._sidebar.clear_selection()
        self._chat.open_conversation(None)
        self._navigation.pop_to_tag("chat")
        self._split.set_show_content(True)
        self._chat.focus_entry()

    def open_conversation(self, conversation_id: int | None) -> None:
        """Select a stored conversation (used when the window is rebuilt)."""
        if conversation_id is None:
            return
        self._chat.open_conversation(conversation_id)
        self.refresh_sidebar(select_id=conversation_id)

    def set_conversation_title(self, title: str | None) -> None:
        self._title.set_title(title or self._t("chat.new_title"))

    def _on_select_conversation(self, conversation_id: int) -> None:
        self._navigation.pop_to_tag("chat")
        self._chat.open_conversation(conversation_id)
        self._split.set_show_content(True)

    def _on_delete_conversation(self, conversation_id: int) -> None:
        def delete() -> None:
            self.services.store.delete_conversation(conversation_id)
            if self._chat.conversation_id == conversation_id:
                self._chat.open_conversation(None)
            self.refresh_sidebar()

        confirm(
            self, heading=self._t("sidebar.delete.heading"), body=self._t("sidebar.delete.body"),
            confirm_label=self._t("sidebar.delete"), cancel_label=self._t("dialog.cancel"), on_confirm=delete,
        )

    def on_conversations_deleted(self) -> None:
        self._chat.open_conversation(None)
        self.refresh_sidebar()

    # -- Library ------------------------------------------------------------------

    def open_library(self) -> None:
        if self._navigation.get_visible_page().get_tag() != "library":
            self._navigation.push(self._library)
        self._split.set_show_content(True)
        self._library.refresh()

    def rebuild_index(self) -> None:
        self.open_library()
        self._library.rebuild()

    def on_library_changed(self) -> None:
        self._chat.refresh_books()

    # -- Busy state and feedback --------------------------------------------------

    @property
    def is_busy(self) -> bool:
        return self._busy is not None

    def set_busy(self, kind: str | None) -> None:
        """Record what is running (``"asking"``, ``"indexing"`` or None) and lock conflicting controls."""
        self._busy = kind
        self._sidebar.set_sensitive(kind != "asking")
        self._chat.set_input_enabled(kind != "indexing")
        self._library.set_actions_enabled(kind is None)

    def show_toast(self, message: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=message))

    def _on_download_event(self, event: DownloadEvent) -> None:
        """Tell the user how a download ended, whether or not Preferences is still open."""
        name = model_name(event.option, self._t)
        if event.kind is DownloadEventKind.FINISHED:
            toast = Adw.Toast(title=self._t("prefs.models.done", name=name))
            if self.services.engine is not None:    # Otherwise the new model is used when the models first load.
                toast.set_button_label(self._t("prefs.models.done.reload"))
                toast.connect("button-clicked", lambda _toast: self.reload_engine())
        elif event.kind is DownloadEventKind.CANCELLED:
            toast = Adw.Toast(title=self._t("prefs.models.cancelled"))
        elif event.kind is DownloadEventKind.FAILED:
            error = event.error
            if isinstance(error, NotEnoughSpaceError):
                title = self._t(
                    "prefs.models.nospace", needed=size_label(error.needed), available=size_label(error.available),
                )
            else:
                title = self._t("prefs.models.failed", error=str(error))
            toast = Adw.Toast(title=title, timeout=10)
        else:
            return
        dialog = self.get_visible_dialog()
        # A dialog with its own toast area (Preferences, the welcome guide) shows the toast where the user is looking.
        (dialog if hasattr(dialog, "add_toast") else self._toasts).add_toast(toast)

    def notify_answer(self, preview: str) -> None:
        """Send a desktop notification when an answer finishes while the window is in the background."""
        if not self.services.settings.app.notify_on_answer or self.is_active():
            return
        if winsupport.send_toast(self._t("notify.title"), preview):    # GLib has no notification backend on Windows.
            return
        notification = Gio.Notification.new(self._t("notify.title"))
        notification.set_body(preview)
        self.get_application().send_notification("answer-ready", notification)

    # -- Closing ------------------------------------------------------------------

    def _on_close_request(self, *_args: object) -> bool:
        if not (self.services.worker.is_busy or self.services.downloads.active):
            return False
        confirm(
            self, heading=self._t("close.heading"), body=self._t("close.body"),
            confirm_label=self._t("close.confirm"), cancel_label=self._t("dialog.cancel"),
            on_confirm=self.destroy,
        )
        return True
