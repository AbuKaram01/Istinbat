# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The conversation page: message list, search-scope picker and question entry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import APP_ID
from ..core.engine import AskResult, AskStatus
from ..core.history import ChatHistory
from ..services import Task
from .message_entry import MessageEntry
from .messages import AssistantCard, UserBubble
from .scope import ScopeButton

if TYPE_CHECKING:
    from .window import MainWindow

_MAX_CONTENT_WIDTH = 780
_MESSAGE_GAP = 14
_SCROLL_RETRY_MS = 120
_NOTIFICATION_PREVIEW_CHARS = 80


class ChatView(Gtk.Box):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._services = window.services
        self._t = window.services.translate
        self._conversation_id: int | None = None
        self._draft_scope: list[str] | None = None
        self._history = self._new_history()
        self._task: Task | None = None
        self._asking = False

        self.scope_button = ScopeButton(self._t, self._on_scope_changed)
        self._empty = Adw.StatusPage(
            icon_name=APP_ID,
            title=self._t("chat.empty.title"),
            description=self._t("chat.empty.description"),
        )
        self._messages = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=_MESSAGE_GAP,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18,
        )
        self._scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._scroller.set_child(Adw.Clamp(maximum_size=_MAX_CONTENT_WIDTH, child=self._messages))
        self._stack = Gtk.Stack()
        self._stack.add_named(self._empty, "empty")
        self._stack.add_named(self._scroller, "messages")

        self._entry = MessageEntry(self._t("chat.placeholder"), self._t("chat.input.tooltip"), self._on_send_clicked)
        self._send = Gtk.Button(valign=Gtk.Align.END, margin_bottom=2)
        self._send.add_css_class("circular")
        self._send.connect("clicked", self._on_send_clicked)
        self._show_send_button()

        bar = Gtk.Box(spacing=10, margin_top=8, margin_bottom=14, margin_start=18, margin_end=18, valign=Gtk.Align.END)
        bar.append(self._entry)
        bar.append(self._send)
        self.append(self._stack)
        self.append(Adw.Clamp(maximum_size=_MAX_CONTENT_WIDTH, child=bar))

    # -- State exposed to the window ----------------------------------------------

    @property
    def conversation_id(self) -> int | None:
        return self._conversation_id

    def refresh_books(self) -> None:
        """Show the indexed books in the scope picker (after the library or the engine changed)."""
        self._refresh_scope(self._current_scope())

    def set_input_enabled(self, enabled: bool) -> None:
        self._entry.set_sensitive(enabled)
        self._send.set_sensitive(enabled or self._asking)

    def open_conversation(self, conversation_id: int | None) -> None:
        """Show a stored conversation, or the empty new-conversation state for ``None``."""
        self._conversation_id = conversation_id
        self._clear_messages()
        if conversation_id is None:
            self._draft_scope = None
            self._history = self._new_history()
            self._stack.set_visible_child_name("empty")
            self._refresh_scope(None)
            self._window.set_conversation_title(None)
            return

        store = self._services.store
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            self.open_conversation(None)
            return
        turns = store.turns(conversation_id)
        for turn in turns:
            self._messages.append(UserBubble(self._t, turn.question))
            card = AssistantCard(self._t)
            card.show_stored(turn.answer, turn.sources, turn.seconds)
            self._messages.append(card)
        memory = self._services.settings.memory
        self._history = store.history_for(conversation_id, memory.history_turns, memory.history_answer_chars)
        self._stack.set_visible_child_name("messages" if turns else "empty")
        self._refresh_scope(conversation.scope)
        self._window.set_conversation_title(conversation.title)
        self._scroll_to_end()

    def focus_entry(self) -> None:
        self._entry.grab_focus()

    # -- Sending ------------------------------------------------------------------

    def _on_send_clicked(self, *_args: object) -> None:
        if self._asking:
            self._stop()
        else:
            self._submit(self._entry.get_text().strip())

    def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self._send.set_sensitive(False)

    def _submit(self, question: str) -> None:
        if not question or self._window.is_busy:
            return
        engine = self._services.engine
        if engine is None:
            # The models load the first time they are needed; the question stays in the entry meanwhile.
            self._window.ensure_engine(lambda: self._submit(question))
            return
        self._ensure_conversation()
        scope = self._current_scope()
        history = self._history
        conversation_id = self._conversation_id
        worker = self._services.worker

        card = AssistantCard(self._t)
        self._messages.append(UserBubble(self._t, question))
        self._messages.append(card)
        self._stack.set_visible_child_name("messages")
        self._entry.set_text("")
        self._set_asking(True)
        self._scroll_to_end()

        def job(task: Task) -> AskResult:
            return engine.ask(
                question,
                history,
                on_stage=lambda stage, event, _seconds: worker.post(card.on_stage, stage, event),
                on_token=lambda fragment: worker.post(self._on_fragment, card, fragment),
                cancel=task.is_cancelled,
                books=scope,
            )

        self._task = worker.submit(
            job,
            on_done=lambda result: self._on_result(card, conversation_id, result),
            on_error=lambda error: self._on_error(card, error),
        )

    def _ensure_conversation(self) -> None:
        if self._conversation_id is not None:
            return
        conversation = self._services.store.create_conversation(scope=self._draft_scope)
        self._conversation_id = conversation.id
        self._history = self._new_history()
        self._window.refresh_sidebar(select_id=conversation.id)

    def _on_fragment(self, card: AssistantCard, fragment: str) -> None:
        card.append_text(fragment)
        self._scroll_to_end()

    def _on_result(self, card: AssistantCard, conversation_id: int | None, result: AskResult) -> None:
        card.finish(result)
        self._set_asking(False)
        if result.status is AskStatus.OK and conversation_id is not None:
            store = self._services.store
            store.add_result(conversation_id, result)
            self._window.set_conversation_title(store.get_conversation(conversation_id).title)
            self._window.refresh_sidebar(select_id=conversation_id)
            self._window.notify_answer(result.question[:_NOTIFICATION_PREVIEW_CHARS])
        self._scroll_to_end()

    def _on_error(self, card: AssistantCard, error: Exception) -> None:
        card.show_error(str(error))
        self._set_asking(False)

    def _set_asking(self, asking: bool) -> None:
        self._asking = asking
        self._task = self._task if asking else None
        self._show_send_button()
        self._window.set_busy("asking" if asking else None)

    def _show_send_button(self) -> None:
        stop = self._asking
        self._send.set_icon_name("media-playback-stop-symbolic" if stop else "go-up-symbolic")
        self._send.set_tooltip_text(self._t("chat.stop" if stop else "chat.send"))
        self._send.set_sensitive(True)
        for css_class, wanted in (("suggested-action", not stop), ("destructive-action", stop)):
            if wanted:
                self._send.add_css_class(css_class)
            else:
                self._send.remove_css_class(css_class)

    # -- Scope and helpers --------------------------------------------------------

    def _current_scope(self) -> list[str] | None:
        if self._conversation_id is None:
            return self._draft_scope
        conversation = self._services.store.get_conversation(self._conversation_id)
        return conversation.scope if conversation else None

    def _refresh_scope(self, selection: list[str] | None) -> None:
        engine = self._services.engine
        self.scope_button.set_books(engine.books() if engine else self._services.indexed_books(), selection)

    def _on_scope_changed(self, selection: list[str] | None) -> None:
        if self._conversation_id is None:
            self._draft_scope = selection
        else:
            self._services.store.set_scope(self._conversation_id, selection)

    def _new_history(self) -> ChatHistory:
        memory = self._services.settings.memory
        return ChatHistory(memory.history_turns, memory.history_answer_chars)

    def _clear_messages(self) -> None:
        while (child := self._messages.get_first_child()) is not None:
            self._messages.remove(child)

    def _scroll_to_end(self) -> None:
        adjustment = self._scroller.get_vadjustment()

        def scroll() -> bool:
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            return GLib.SOURCE_REMOVE

        GLib.idle_add(scroll)
        GLib.timeout_add(_SCROLL_RETRY_MS, scroll)
