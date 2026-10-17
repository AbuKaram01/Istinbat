# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A widget that draws Markdown: headings, lists, code, tables, quotes and links.

``set_markdown`` can be called many times while an answer streams in. Blocks that
have not changed keep their widgets, so earlier parts stay stable (selection,
scroll position and Copy buttons are not disturbed) and only the changing tail is rebuilt.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango

from ..markdown import (
    Block,
    CodeBlock,
    Heading,
    ListBlock,
    Paragraph,
    Quote,
    Rule,
    Table,
    TableCell,
    parse_markdown,
    plain_text,
)
from .formatting import is_rtl_text

_BLOCK_SPACING = 10
_LIST_SPACING = 4
_HEADING_CLASSES = {1: "title-1", 2: "title-2", 3: "title-3", 4: "title-4"}
_ALIGNMENT = {"left": 0.0, "center": 0.5, "right": 1.0}
_BULLET = "•"
_COMPACT_MAX_CHARS = 60


def _direction_for(text: str) -> Gtk.TextDirection:
    return Gtk.TextDirection.RTL if is_rtl_text(text) else Gtk.TextDirection.LTR


def _open_uri(label: Gtk.Label, uri: str) -> bool:
    """Open a link in the default application. Only reached for links the parser kept as safe."""
    Gtk.UriLauncher.new(uri).launch(label.get_root(), None, lambda *_args: None)
    return True


def _text_label(
    markup: str, plain: str, *, css_class: str | None = None, xalign: float = 0.0, compact: bool = False,
) -> Gtk.Label:
    label = Gtk.Label(use_markup=True, label=markup, wrap=True, selectable=True, xalign=xalign, hexpand=not compact)
    if compact:
        label.set_max_width_chars(_COMPACT_MAX_CHARS)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_direction(_direction_for(plain))
    label.connect("activate-link", _open_uri)
    if css_class:
        label.add_css_class(css_class)
    return label


def _horizontal_scroller() -> Gtk.ScrolledWindow:
    """A scroller that only scrolls sideways and is as tall as its content (for code and tables)."""
    return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER)


class MarkdownView(Gtk.Box):
    """Renders a Markdown string as a vertical stack of block widgets."""

    def __init__(self, translate: Callable[..., str], *, compact: bool = False) -> None:
        """``compact`` sizes text to its content (for chat bubbles) instead of filling the width."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=_BLOCK_SPACING)
        self._translate = translate
        self._compact = compact
        self._blocks: list[Block] = []
        self._widgets: list[Gtk.Widget] = []
        self._markdown = ""
        self._links = True

    @property
    def markdown(self) -> str:
        return self._markdown

    def set_markdown(self, text: str, *, links: bool = True) -> None:
        """Show ``text``, rebuilding only the blocks that changed since the last call.

        ``links=False`` shows link text without making it clickable (used while streaming).
        """
        if text == self._markdown and links == self._links:
            return
        self._markdown, self._links = text, links
        blocks = parse_markdown(text, links=links)

        unchanged = 0
        for old, new in zip(self._blocks, blocks, strict=False):
            if old != new:
                break
            unchanged += 1

        for widget in self._widgets[unchanged:]:
            self.remove(widget)
        del self._widgets[unchanged:]
        for block in blocks[unchanged:]:
            widget = self._build(block)
            self.append(widget)
            self._widgets.append(widget)
        self._blocks = blocks
        self.set_visible(bool(blocks))

    # -- Block widgets ----------------------------------------------------------

    def _build(self, block: Block) -> Gtk.Widget:
        if isinstance(block, Paragraph):
            return _text_label(block.markup, block.plain, compact=self._compact)
        if isinstance(block, Heading):
            css_class = _HEADING_CLASSES.get(block.level, "heading")
            return _text_label(block.markup, block.plain, css_class=css_class, compact=self._compact)
        if isinstance(block, CodeBlock):
            return self._code_block(block)
        if isinstance(block, ListBlock):
            return self._list(block)
        if isinstance(block, Quote):
            return self._quote(block)
        if isinstance(block, Table):
            return self._table(block)
        if isinstance(block, Rule):
            return Gtk.Separator(margin_top=4, margin_bottom=4)
        raise TypeError(f"Unsupported block: {block!r}")

    def _column(self, blocks: tuple[Block, ...], spacing: int = _LIST_SPACING) -> Gtk.Box:
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, hexpand=not self._compact)
        for block in blocks:
            column.append(self._build(block))
        return column

    def _code_block(self, block: CodeBlock) -> Gtk.Widget:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        frame.add_css_class("md-code")
        frame.set_direction(Gtk.TextDirection.LTR)   # Source code always reads left to right.

        copy = Gtk.Button(icon_name="edit-copy-symbolic", css_classes=["flat", "circular"])
        copy.set_tooltip_text(self._translate("chat.copy"))
        copy.connect("clicked", lambda button: button.get_clipboard().set(block.code))
        header = Gtk.Box(spacing=6)
        header.set_direction(Gtk.TextDirection.LTR)
        header.append(Gtk.Label(label=block.language, xalign=0, hexpand=True, css_classes=["dim-label", "caption"]))
        header.append(copy)

        code = Gtk.Label(label=block.code, selectable=True, xalign=0, css_classes=["monospace"])
        code.set_direction(Gtk.TextDirection.LTR)
        scroller = _horizontal_scroller()
        scroller.set_propagate_natural_height(True)
        scroller.set_direction(Gtk.TextDirection.LTR)
        scroller.set_child(code)
        frame.append(header)
        frame.append(scroller)
        return frame

    def _list(self, block: ListBlock) -> Gtk.Widget:
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_LIST_SPACING)
        for index, item in enumerate(block.items):
            marker_text = f"{block.start + index}." if block.ordered else _BULLET
            marker = Gtk.Label(label=marker_text, xalign=1.0, valign=Gtk.Align.START, css_classes=["dim-label"])
            marker.set_width_chars(2)
            row = Gtk.Box(spacing=8)
            row.set_direction(_direction_for(" ".join(plain_text(child) for child in item.blocks)))
            row.append(marker)
            row.append(self._column(item.blocks))
            column.append(row)
        return column

    def _quote(self, block: Quote) -> Gtk.Widget:
        quote = self._column(block.blocks, _BLOCK_SPACING)
        quote.add_css_class("md-quote")
        quote.set_direction(_direction_for(plain_text(block)))
        return quote

    def _table(self, block: Table) -> Gtk.Widget:
        grid = Gtk.Grid(column_homogeneous=False, halign=Gtk.Align.START, valign=Gtk.Align.START)
        grid.add_css_class("md-table")
        grid.set_direction(_direction_for(plain_text(block)))
        for column, cell in enumerate(block.header):
            grid.attach(self._cell(cell, header=True), column, 0, 1, 1)
        for row_index, row in enumerate(block.rows, start=1):
            for column, cell in enumerate(row):
                grid.attach(self._cell(cell, header=False), column, row_index, 1, 1)

        scroller = _horizontal_scroller()
        scroller.set_propagate_natural_height(True)
        scroller.set_child(grid)
        return scroller

    @staticmethod
    def _cell(cell: TableCell, *, header: bool) -> Gtk.Widget:
        markup = f"<b>{cell.markup}</b>" if header else cell.markup
        label = _text_label(markup, cell.plain, xalign=_ALIGNMENT.get(cell.align, 0.0))
        label.set_hexpand(False)
        label.add_css_class("md-cell")
        if header:
            label.add_css_class("md-cell-header")
        return label
