# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Markdown parsing into a small, toolkit-independent document model.

``parse_markdown`` turns CommonMark text (plus tables and strikethrough) into
immutable block objects. Inline formatting is converted to Pango markup, with
every piece of user text escaped, so a model can never inject markup. Raw HTML
is not interpreted: it is shown as plain text. Links are limited to safe
schemes, and images are replaced by their alt text because the app is offline.

The GTK widgets that draw these blocks live in ``istinbat.gui.markdown_view``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

SAFE_LINK_SCHEMES = frozenset({"http", "https", "mailto"})

_INLINE_CODE_STYLE = 'font_family="monospace" bgcolor="#808080" bgalpha="25%"'


@dataclass(frozen=True)
class Paragraph:
    markup: str     # Pango markup.
    plain: str      # The same text without formatting, used to pick the text direction.


@dataclass(frozen=True)
class Heading:
    level: int
    markup: str
    plain: str


@dataclass(frozen=True)
class CodeBlock:
    code: str
    language: str


@dataclass(frozen=True)
class Rule:
    pass


@dataclass(frozen=True)
class Quote:
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ListItem:
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ListBlock:
    ordered: bool
    start: int
    items: tuple[ListItem, ...]


@dataclass(frozen=True)
class TableCell:
    markup: str
    plain: str
    align: str      # "left", "right", "center" or "" for the default.


@dataclass(frozen=True)
class Table:
    header: tuple[TableCell, ...]
    rows: tuple[tuple[TableCell, ...], ...]


Block = Paragraph | Heading | CodeBlock | Rule | Quote | ListBlock | Table

_PARSER = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(["table", "strikethrough"])


def parse_markdown(text: str, *, links: bool = True) -> list[Block]:
    """Parse Markdown ``text`` into top-level blocks.

    With ``links=False`` link text is kept but nothing is clickable. The interface uses that
    while an answer is still streaming, before it has been checked.
    """
    root = SyntaxTreeNode(_PARSER.parse(text))
    return _Converter(links).blocks(root.children)


def plain_text(block: Block) -> str:
    """The visible text of a block, for choosing a direction. Code never counts."""
    if isinstance(block, (Paragraph, Heading)):
        return block.plain
    if isinstance(block, Quote):
        return " ".join(plain_text(child) for child in block.blocks)
    if isinstance(block, ListBlock):
        return " ".join(plain_text(child) for item in block.items for child in item.blocks)
    if isinstance(block, Table):
        return " ".join(cell.plain for cell in block.header)
    return ""


def escape_markup(text: str, *, attribute: bool = False) -> str:
    """Escape ``text`` for Pango markup (and for use inside an attribute value if asked)."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if attribute:
        text = text.replace('"', "&quot;").replace("'", "&#39;")
    return text


def is_safe_link(uri: str) -> bool:
    return urlparse(uri.strip()).scheme.lower() in SAFE_LINK_SCHEMES


# -- Conversion ---------------------------------------------------------------

class _Converter:
    """Turns markdown-it syntax-tree nodes into blocks and Pango markup."""

    def __init__(self, links: bool) -> None:
        self._links = links

    def blocks(self, nodes: list[SyntaxTreeNode]) -> list[Block]:
        blocks: list[Block] = []
        for node in nodes:
            block = self._block(node)
            if block is not None:
                blocks.append(block)
        return blocks

    def _block(self, node: SyntaxTreeNode) -> Block | None:
        kind = node.type
        if kind == "paragraph":
            markup, plain = self._inline_of(node)
            return Paragraph(markup, plain)
        if kind == "heading":
            markup, plain = self._inline_of(node)
            return Heading(int(node.tag[1:]), markup, plain)
        if kind in ("fence", "code_block"):
            language = (node.info or "").split(maxsplit=1)[0] if node.info else ""
            return CodeBlock(node.content.rstrip("\n"), language)
        if kind == "hr":
            return Rule()
        if kind == "blockquote":
            return Quote(tuple(self.blocks(node.children)))
        if kind in ("bullet_list", "ordered_list"):
            start = int(node.attrs.get("start", 1)) if kind == "ordered_list" else 1
            items = tuple(ListItem(tuple(self.blocks(item.children))) for item in node.children)
            return ListBlock(kind == "ordered_list", start, items)
        if kind == "table":
            return self._table(node)
        if kind == "html_block":
            return Paragraph(escape_markup(node.content.strip()), node.content.strip())
        return None

    def _table(self, node: SyntaxTreeNode) -> Table:
        header: tuple[TableCell, ...] = ()
        rows: list[tuple[TableCell, ...]] = []
        for section in node.children:
            for row in section.children:
                cells = tuple(self._cell(cell) for cell in row.children)
                if section.type == "thead":
                    header = cells
                else:
                    rows.append(cells)
        return Table(header, tuple(rows))

    def _cell(self, node: SyntaxTreeNode) -> TableCell:
        markup, plain = self._inline_of(node)
        style = str(node.attrs.get("style", ""))
        align = style.removeprefix("text-align:") if style.startswith("text-align:") else ""
        return TableCell(markup, plain, align)

    # -- Inline content ---------------------------------------------------------

    def _inline_of(self, node: SyntaxTreeNode) -> tuple[str, str]:
        """Convert a block's inline child to (Pango markup, plain text)."""
        if not node.children:
            return "", ""
        markup: list[str] = []
        plain: list[str] = []
        self._inline_children(node.children[0].children, markup, plain)
        return "".join(markup), "".join(plain).strip()

    def _inline_children(self, nodes: list[SyntaxTreeNode], markup: list[str], plain: list[str]) -> None:
        for node in nodes:
            kind = node.type
            if kind == "text":
                markup.append(escape_markup(node.content))
                plain.append(node.content)
            elif kind in ("softbreak", "hardbreak"):
                markup.append("\n")
                plain.append(" ")
            elif kind == "code_inline":
                markup.append(f"<span {_INLINE_CODE_STYLE}>{escape_markup(node.content)}</span>")
            elif kind in ("strong", "em", "s"):
                tag = {"strong": "b", "em": "i", "s": "s"}[kind]
                markup.append(f"<{tag}>")
                self._inline_children(node.children, markup, plain)
                markup.append(f"</{tag}>")
            elif kind == "link":
                clickable = self._links and is_safe_link(str(node.attrs.get("href", "")))
                href = escape_markup(str(node.attrs.get("href", "")), attribute=True)
                markup.append(f'<a href="{href}">' if clickable else "")
                self._inline_children(node.children, markup, plain)
                markup.append("</a>" if clickable else "")
            elif kind == "image":
                alt = "".join(child.content for child in node.children if child.type == "text") or node.content
                markup.append(f"<i>{escape_markup(alt)}</i>")
                plain.append(alt)
            else:  # Unknown inline kinds (for example html_inline when enabled) degrade to text.
                markup.append(escape_markup(node.content))
                plain.append(node.content)
