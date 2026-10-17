# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small widget helpers shared by several pages."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from .formatting import is_rtl_text


def apply_text_direction(widget: Gtk.Widget, text: str) -> None:
    """Lay ``widget`` out in the direction of ``text`` itself, not of the interface.

    An Arabic answer inside the English interface should read and align right-to-left.
    """
    widget.set_direction(Gtk.TextDirection.RTL if is_rtl_text(text) else Gtk.TextDirection.LTR)


def confirm(
    parent: Gtk.Widget,
    *,
    heading: str,
    body: str,
    confirm_label: str,
    cancel_label: str,
    on_confirm: Callable[[], None],
    destructive: bool = True,
) -> None:
    """Ask the user to confirm an action; ``on_confirm`` runs only if they accept."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", cancel_label)
    dialog.add_response("confirm", confirm_label)
    appearance = Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
    dialog.set_response_appearance("confirm", appearance)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _dialog, response: on_confirm() if response == "confirm" else None)
    dialog.present(parent)


def window_buttons(translate: Callable[..., str]) -> tuple[Gtk.Button, Gtk.MenuButton]:
    """Create the language switch and the primary menu shown in every header bar."""
    language = Gtk.Button(label=translate("language.switch_to"))
    language.add_css_class("flat")
    language.set_tooltip_text(translate("language.tooltip"))
    language.set_action_name("app.toggle-language")

    menu = Gio.Menu()
    menu.append(translate("menu.preferences"), "app.preferences")
    menu.append(translate("menu.about"), "app.about")
    menu.append(translate("menu.quit"), "app.quit")
    primary = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
    primary.set_tooltip_text(translate("menu.tooltip"))
    return language, primary
