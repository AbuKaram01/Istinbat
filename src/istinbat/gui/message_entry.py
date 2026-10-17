# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Multi-line message input: Enter sends, Shift+Enter inserts a new line."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

_MIN_HEIGHT = 40
_MAX_HEIGHT = 168
_SUBMIT_KEYS = (Gdk.KEY_Return, Gdk.KEY_KP_Enter)


class MessageEntry(Gtk.Box):
    """A growing text box with a placeholder, sized for chat messages (and Markdown)."""

    def __init__(self, placeholder: str, tooltip: str, on_submit: Callable[[], None]) -> None:
        super().__init__(hexpand=True)
        self._on_submit = on_submit

        self._view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
        self._view.add_css_class("message-input")
        self._view.set_top_margin(10)
        self._view.set_bottom_margin(10)
        self._view.set_left_margin(14)
        self._view.set_right_margin(14)
        self._view.set_tooltip_text(tooltip)
        self._buffer = self._view.get_buffer()
        self._buffer.connect("changed", self._on_changed)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self._view.add_controller(keys)

        self._placeholder = Gtk.Label(
            label=placeholder, xalign=0, halign=Gtk.Align.START, valign=Gtk.Align.START,
            margin_top=10, margin_start=14, margin_end=14, css_classes=["dim-label"], can_target=False,
        )
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=_MIN_HEIGHT)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(_MAX_HEIGHT)
        scroller.set_child(self._view)

        overlay = Gtk.Overlay(hexpand=True, child=scroller)
        overlay.add_overlay(self._placeholder)
        frame = Gtk.Frame(hexpand=True, child=overlay)
        frame.add_css_class("message-frame")
        self.append(frame)

    # -- Text ---------------------------------------------------------------------

    def get_text(self) -> str:
        return self._buffer.get_text(self._buffer.get_start_iter(), self._buffer.get_end_iter(), False)

    def set_text(self, text: str) -> None:
        self._buffer.set_text(text)

    def do_grab_focus(self) -> bool:
        return self._view.grab_focus()

    # -- Events -------------------------------------------------------------------

    def _on_changed(self, _buffer: Gtk.TextBuffer) -> None:
        self._placeholder.set_visible(self._buffer.get_char_count() == 0)

    def _on_key_pressed(
        self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, state: Gdk.ModifierType,
    ) -> bool:
        """Send on Enter; let Shift+Enter fall through so the text view inserts a new line."""
        if keyval in _SUBMIT_KEYS and not state & Gdk.ModifierType.SHIFT_MASK:
            self._on_submit()
            return True
        return False
