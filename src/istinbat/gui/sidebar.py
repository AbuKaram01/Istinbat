# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The conversation list and the Library / Preferences shortcuts."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from ..storage import Conversation
from .formatting import day_bucket
from .widgets import apply_text_direction


class Sidebar(Adw.NavigationPage):
    def __init__(
        self,
        translate: Callable[..., str],
        *,
        on_select: Callable[[int], None],
        on_delete: Callable[[int], None],
        on_new: Callable[[], None],
        on_library: Callable[[], None],
        on_preferences: Callable[[], None],
    ) -> None:
        super().__init__(title=translate("sidebar.title"))
        self._translate = translate
        self._on_select = on_select
        self._on_delete = on_delete
        self._updating = False

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        new_button = Gtk.Button(icon_name="list-add-symbolic")
        new_button.set_tooltip_text(translate("sidebar.new"))
        new_button.connect("clicked", lambda _b: on_new())
        header.pack_start(new_button)
        view.add_top_bar(header)

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._list.add_css_class("navigation-sidebar")
        self._list.connect("row-selected", self._on_row_selected)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self._list)
        view.set_content(scroller)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6)
        for icon, key, callback in (
            ("accessories-dictionary-symbolic", "sidebar.library", on_library),
            ("emblem-system-symbolic", "sidebar.preferences", on_preferences),
        ):
            button = Gtk.Button(css_classes=["flat"])
            content = Adw.ButtonContent(icon_name=icon, label=translate(key), halign=Gtk.Align.START)
            button.set_child(content)
            button.connect("clicked", lambda _b, cb=callback: cb())
            footer.append(button)
        view.add_bottom_bar(footer)
        self.set_child(view)

    def set_conversations(self, conversations: Sequence[Conversation], selected_id: int | None) -> None:
        """Rebuild the list; the row of ``selected_id`` (if any) is highlighted."""
        self._updating = True
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)
        now = time.time()
        for conversation in conversations:
            row = self._build_row(conversation, now)
            self._list.append(row)
            if conversation.id == selected_id:
                self._list.select_row(row)
        self._updating = False

    def clear_selection(self) -> None:
        self._updating = True
        self._list.unselect_all()
        self._updating = False

    def _build_row(self, conversation: Conversation, now: float) -> Gtk.ListBoxRow:
        title = conversation.title or self._translate("sidebar.untitled")
        bucket = day_bucket(conversation.updated_at, now)
        subtitle = self._translate(f"time.{bucket}") if bucket in ("today", "yesterday") else bucket

        title_label = Gtk.Label(
            label=title, xalign=0, ellipsize=Pango.EllipsizeMode.END, single_line_mode=True, css_classes=["heading"],
        )
        apply_text_direction(title_label, title)
        subtitle_label = Gtk.Label(label=subtitle, xalign=0, css_classes=["dim-label", "caption"])
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(title_label)
        text.append(subtitle_label)

        delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        delete.add_css_class("flat")
        delete.add_css_class("circular")
        delete.set_tooltip_text(self._translate("sidebar.delete"))
        delete.connect("clicked", lambda _b, cid=conversation.id: self._on_delete(cid))

        box = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=2)
        box.append(text)
        box.append(delete)
        row = Gtk.ListBoxRow(child=box)
        row.conversation_id = conversation.id  # type: ignore[attr-defined]
        return row

    def _on_row_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if not self._updating and row is not None:
            self._on_select(row.conversation_id)  # type: ignore[attr-defined]
