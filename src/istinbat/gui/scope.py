# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Search-scope picker: choose which books a conversation searches."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

_POPOVER_SPACING = 6


class ScopeButton(Gtk.MenuButton):
    """Header button with a popover listing the indexed books as check boxes.

    ``selection`` is None when every book is searched. The last checked book cannot
    be unchecked, because an empty scope would make every question unanswerable.
    """

    def __init__(self, translate: Callable[..., str], on_changed: Callable[[list[str] | None], None]) -> None:
        super().__init__()
        self._translate = translate
        self._on_changed = on_changed
        self._books: list[str] = []
        self._selection: list[str] | None = None
        self._checks: dict[str, Gtk.CheckButton] = {}
        self._updating = False

        self.set_icon_name("accessories-dictionary-symbolic")
        self.set_always_show_arrow(True)
        self.set_tooltip_text(translate("scope.tooltip"))
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_POPOVER_SPACING)
        for margin in ("top", "bottom", "start", "end"):
            getattr(self._content, f"set_margin_{margin}")(10)
        popover = Gtk.Popover(child=self._content)
        self.set_popover(popover)

    def set_books(self, books: Sequence[str], selection: list[str] | None) -> None:
        """Replace the list of indexed books and the current selection (None means all)."""
        self._books = list(books)
        self._selection = self._normalize(selection)
        self._rebuild()

    def _normalize(self, selection: list[str] | None) -> list[str] | None:
        if selection is None:
            return None
        valid = [book for book in self._books if book in selection]
        return valid if valid and len(valid) < len(self._books) else None

    def _rebuild(self) -> None:
        while (child := self._content.get_first_child()) is not None:
            self._content.remove(child)
        self._checks.clear()

        self.set_sensitive(bool(self._books))
        self._content.append(Gtk.Label(label=self._translate("scope.title"), xalign=0, css_classes=["heading"]))
        self._content.append(
            Gtk.Label(label=self._translate("scope.hint"), xalign=0, css_classes=["dim-label", "caption"])
        )
        self._updating = True
        for book in self._books:
            check = Gtk.CheckButton(label=book)
            check.set_active(self._selection is None or book in self._selection)
            check.connect("toggled", self._on_toggled, book)
            self._checks[book] = check
            self._content.append(check)
        self._updating = False

        select_all = Gtk.Button(label=self._translate("scope.select_all"), css_classes=["flat"])
        select_all.connect("clicked", self._on_select_all)
        self._content.append(select_all)
        self._refresh_label()

    def _on_toggled(self, check: Gtk.CheckButton, book: str) -> None:
        if self._updating:
            return
        chosen = [name for name, box in self._checks.items() if box.get_active()]
        if not chosen:
            self._updating = True
            check.set_active(True)
            self._updating = False
            return
        self._commit(chosen)

    def _on_select_all(self, _button: Gtk.Button) -> None:
        self._updating = True
        for check in self._checks.values():
            check.set_active(True)
        self._updating = False
        self._commit(list(self._books))

    def _commit(self, chosen: list[str]) -> None:
        self._selection = None if len(chosen) == len(self._books) else chosen
        self._refresh_label()
        self._on_changed(self._selection)

    def _refresh_label(self) -> None:
        if self._selection is None:
            self.set_label(self._translate("scope.all_books"))
        else:
            self.set_label(self._translate("scope.some_books", count=len(self._selection), total=len(self._books)))
