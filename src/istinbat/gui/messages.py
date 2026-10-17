# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Chat message widgets: the user's question bubble and the assistant's answer card."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from ..core.engine import AskResult, AskStatus
from ..core.progress import Stage, StageEvent
from .formatting import duration_parts
from .markdown_view import MarkdownView
from .widgets import apply_text_direction

_MESSAGE_SPACING = 10
_RENDER_INTERVAL_MS = 80
_STAGE_LABEL_KEYS = {
    Stage.REWRITE: "stage.rewrite",
    Stage.VECTOR: "stage.vector",
    Stage.BM25: "stage.bm25",
    Stage.RERANK: "stage.rerank",
    Stage.LLM: "stage.llm",
}


def _wrapping_label(text: str = "", *, selectable: bool = True) -> Gtk.Label:
    label = Gtk.Label(label=text, wrap=True, selectable=selectable, xalign=0, hexpand=True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return label


class UserBubble(Gtk.Box):
    """The user's question, aligned to the start of the line. It may contain Markdown."""

    def __init__(self, translate: Callable[..., str], text: str) -> None:
        super().__init__(halign=Gtk.Align.START)
        self.add_css_class("user-bubble")
        view = MarkdownView(translate, compact=True)
        view.set_markdown(text)
        self.append(view)


class SourcesSection(Gtk.Expander):
    """The books and passages an answer was drawn from, collapsed by default."""

    def __init__(self, translate: Callable[..., str], sources: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(label=translate("chat.sources", count=len(sources)))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_MESSAGE_SPACING, margin_top=8)
        for source in sources:
            title = Gtk.Label(label=source["book"], xalign=0, css_classes=["heading"])
            snippet = _wrapping_label(source["text"])
            snippet.add_css_class("source-snippet")
            apply_text_direction(snippet, source["text"])
            box.append(title)
            box.append(snippet)
        self.set_child(box)


class AssistantCard(Gtk.Box):
    """One answer: live progress while working, then Markdown text, sources and timing."""

    def __init__(self, translate: Callable[..., str]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=_MESSAGE_SPACING)
        self._translate = translate
        self.add_css_class("card")
        self.add_css_class("answer-card")

        self._spinner = Gtk.Spinner(spinning=True)
        self._stage = Gtk.Label(xalign=0, css_classes=["dim-label"])
        self._progress_row = Gtk.Box(spacing=8)
        self._progress_row.append(self._spinner)
        self._progress_row.append(self._stage)

        self._answer = MarkdownView(translate)
        self._footer = Gtk.Label(xalign=0, hexpand=True, css_classes=["dim-label", "caption"])
        self._copy = Gtk.Button(icon_name="edit-copy-symbolic", css_classes=["flat", "circular"])
        self._copy.set_tooltip_text(translate("chat.copy"))
        self._copy.connect("clicked", lambda button: button.get_clipboard().set(self._text))
        self._footer_row = Gtk.Box(spacing=6, visible=False)
        self._footer_row.append(self._footer)
        self._footer_row.append(self._copy)

        self._text = ""
        self._render_source: int | None = None
        self._sources: SourcesSection | None = None

        self.append(self._progress_row)
        self.append(self._answer)
        self.append(self._footer_row)

    @property
    def text(self) -> str:
        """The raw Markdown of the answer, exactly as the model wrote it."""
        return self._text

    # -- Live updates ---------------------------------------------------------

    def on_stage(self, stage: Stage, event: StageEvent) -> None:
        if event is StageEvent.START:
            self._stage.set_label(self._translate(_STAGE_LABEL_KEYS[stage]))

    def append_text(self, fragment: str) -> None:
        """Add streamed text; rendering is batched so a fast stream does not rebuild widgets per token."""
        self._text += fragment
        if self._render_source is None:
            self._render_source = GLib.timeout_add(_RENDER_INTERVAL_MS, self._render_pending)

    def _render_pending(self) -> bool:
        self._render_source = None
        self._answer.set_markdown(self._text, links=False)   # Not checked yet: nothing clickable.
        return GLib.SOURCE_REMOVE

    def do_unroot(self) -> None:
        self._cancel_pending_render()
        Gtk.Box.do_unroot(self)

    def _cancel_pending_render(self) -> None:
        if self._render_source is not None:
            GLib.source_remove(self._render_source)
            self._render_source = None

    # -- Final states ---------------------------------------------------------

    def finish(self, result: AskResult) -> None:
        """Show the final answer (or the localized status message) with sources and timing."""
        self._stop_progress()
        if result.status in (AskStatus.NO_BOOKS, AskStatus.NO_RESULTS, AskStatus.BLOCKED):
            self._set_answer(self._translate(f"status.{result.status.value}"))
            return
        self._set_answer(result.answer)
        if result.status is AskStatus.CANCELLED:
            self._set_footer(self._translate("status.cancelled"))
            return
        self._show_sources([{"book": s.book, "text": s.text} for s in result.sources])
        self._show_duration(result.total_seconds)

    def show_stored(self, answer: str, sources: Sequence[Mapping[str, Any]], seconds: float | None) -> None:
        """Render a turn loaded from storage."""
        self._stop_progress()
        self._set_answer(answer)
        self._show_sources(sources)
        self._show_duration(seconds) if seconds is not None else self._footer_row.set_visible(bool(answer))

    def show_error(self, message: str) -> None:
        self._stop_progress()
        self._set_answer(self._translate("chat.error", message=message))
        self._answer.add_css_class("error")

    # -- Internals ------------------------------------------------------------

    def _stop_progress(self) -> None:
        self._spinner.set_spinning(False)
        self._progress_row.set_visible(False)

    def _set_answer(self, text: str) -> None:
        self._cancel_pending_render()
        self._text = text
        self._answer.set_markdown(text)
        self._footer_row.set_visible(bool(text))

    def _set_footer(self, text: str) -> None:
        self._footer.set_label(text)
        self._footer_row.set_visible(True)

    def _show_sources(self, sources: Sequence[Mapping[str, Any]]) -> None:
        if sources and self._sources is None:
            self._sources = SourcesSection(self._translate, sources)
            self.insert_child_after(self._sources, self._answer)

    def _show_duration(self, seconds: float) -> None:
        key, params = duration_parts(seconds)
        self._set_footer(self._translate(key, **params))
