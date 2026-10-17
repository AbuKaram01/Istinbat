# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Markdown widgets, the multi-line input and Markdown in the chat. Needs a display."""

import os

import pytest

os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent"

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk
except (ValueError, ImportError):
    pytest.skip("GTK 4 / libadwaita are not installed", allow_module_level=True)

if not Gtk.init_check():
    pytest.skip("no display available", allow_module_level=True)

from gui_fakes import MARKDOWN_ANSWER_AR, MARKDOWN_ANSWER_EN
from gui_support import build_app, pump, start

from istinbat.core import AnswerLanguage
from istinbat.gui.markdown_view import MarkdownView
from istinbat.gui.message_entry import MessageEntry
from istinbat.gui.messages import AssistantCard
from istinbat.i18n import Translator

translate = Translator()


def children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def descendants(widget):
    for child in children(widget):
        yield child
        yield from descendants(child)


def labels(widget):
    return [w for w in descendants(widget) if isinstance(w, Gtk.Label)]


def view_for(text):
    view = MarkdownView(translate)
    view.set_markdown(text)
    return view


# -- MarkdownView ---------------------------------------------------------------

def test_every_block_kind_becomes_a_widget():
    view = view_for(MARKDOWN_ANSWER_EN)
    top = list(children(view))
    assert len(top) == 7                  # heading, paragraph, list, quote, table, code, closing paragraph
    classes = [set(w.get_css_classes()) for w in top]
    assert "title-2" in classes[0]                   # "##" heading
    assert any("md-quote" in c for c in classes)
    assert any("md-code" in c for c in classes)
    assert any(isinstance(w, Gtk.ScrolledWindow) for w in top)   # the table


def test_inline_markup_is_rendered_not_shown_literally():
    view = view_for("A **bold** and `code` and [a link](https://example.com) here.")
    text = labels(view)[0].get_text()
    assert text == "A bold and code and a link here." and "*" not in text and "<" not in text


def test_user_text_that_looks_like_markup_is_shown_literally():
    text = labels(view_for("5 < 6 and <b>not bold</b> & more"))[0].get_text()
    assert text == "5 < 6 and <b>not bold</b> & more"


def test_unsafe_links_are_not_clickable():
    label = labels(view_for("[click me](ftp://host/file)"))[0]
    assert label.get_text() == "click me" and "<a " not in label.get_label()


def test_text_direction_is_decided_per_block():
    view = view_for("هذه فقرة عربية\n\nThis is English\n\n- بند عربي\n- English item")
    arabic, english, items = list(children(view))
    assert arabic.get_direction() == Gtk.TextDirection.RTL
    assert english.get_direction() == Gtk.TextDirection.LTR
    rows = list(children(items))
    assert rows[0].get_direction() == Gtk.TextDirection.RTL and rows[1].get_direction() == Gtk.TextDirection.LTR


def test_ordered_lists_use_their_start_number_and_bullets_use_a_dot():
    view = view_for("3. three\n4. four\n\n- bullet")
    ordered, bullets = list(children(view))
    assert [label.get_label() for label in labels(ordered) if label.get_label().endswith(".")] == ["3.", "4."]
    assert "•" in [label.get_label() for label in labels(bullets)]


def test_code_blocks_are_left_to_right_monospace_with_a_copy_button_even_in_arabic():
    view = view_for("نص عربي\n\n```python\nprint('hi')\n```")
    code_frame = list(children(view))[1]
    assert code_frame.get_direction() == Gtk.TextDirection.LTR
    code_label = [w for w in labels(code_frame) if "monospace" in w.get_css_classes()][0]
    assert code_label.get_text() == "print('hi')" and code_label.get_direction() == Gtk.TextDirection.LTR
    copy = [w for w in descendants(code_frame) if isinstance(w, Gtk.Button)][0]
    copy.emit("clicked")                                  # Must not raise.
    assert any(label.get_text() == "python" for label in labels(code_frame))


def test_tables_have_header_cells_and_alignment():
    view = view_for("| Name | Qty |\n|:--|--:|\n| A | 1 |")
    grid = next(w for w in descendants(view) if isinstance(w, Gtk.Grid))
    cells = labels(grid)
    assert [c.get_text() for c in cells] == ["Name", "Qty", "A", "1"]
    assert "md-cell-header" in cells[0].get_css_classes() and "md-cell-header" not in cells[2].get_css_classes()
    assert cells[1].get_xalign() == 1.0 and cells[0].get_xalign() == 0.0


def test_unchanged_blocks_keep_their_widgets_while_the_tail_streams():
    view = view_for("# Title\n\nfirst paragraph")
    title, paragraph = list(children(view))

    view.set_markdown("# Title\n\nfirst paragraph more")
    new_title, new_paragraph = list(children(view))
    assert new_title is title and new_paragraph is not paragraph

    view.set_markdown("# Title\n\nfirst paragraph more\n\n- new list")
    assert list(children(view))[0] is title and len(list(children(view))) == 3


def test_setting_identical_text_changes_nothing_and_empty_text_hides_the_view():
    view = view_for("# Title")
    widget = view.get_first_child()
    view.set_markdown("# Title")
    assert view.get_first_child() is widget
    view.set_markdown("")
    assert not view.get_visible() and view.get_first_child() is None


def test_partial_markdown_never_breaks_rendering():
    view = MarkdownView(translate)
    for partial in ("**bold", "```py\nx =", "| a | b |\n|--", "- ", "> ", "1.", "[x](http", "![a]("):
        view.set_markdown(partial)                        # Streaming shows these intermediate states.


def test_markdown_view_supports_the_arabic_sample_end_to_end():
    view = view_for(MARKDOWN_ANSWER_AR)
    texts = [label.get_text() for label in labels(view)]
    assert "أنواع الذاكرة" in texts and any("RAM" in t for t in texts)


# -- AssistantCard --------------------------------------------------------------

def test_streamed_text_is_rendered_in_batches_and_the_raw_markdown_is_kept():
    card = AssistantCard(translate)
    for fragment in ("## Hea", "ding\n\nSome ", "**bold**"):
        card.append_text(fragment)
    assert card.text == "## Heading\n\nSome **bold**"
    pump(0.3)
    assert [label.get_text() for label in labels(card._answer)] == ["Heading", "Some bold"]


def test_the_card_has_a_copy_button_for_the_raw_markdown():
    card = AssistantCard(translate)
    card.show_stored("**raw** markdown", [], 2.0)
    assert any(isinstance(w, Gtk.Button) for w in descendants(card._footer_row))
    assert card.text == "**raw** markdown"


# -- MessageEntry ----------------------------------------------------------------

def make_entry():
    sent = []
    return MessageEntry("Ask…", "tip", lambda: sent.append(True)), sent


def test_enter_sends_and_shift_enter_does_not():
    entry, sent = make_entry()
    no_modifier, shift = Gdk.ModifierType(0), Gdk.ModifierType.SHIFT_MASK
    assert entry._on_key_pressed(None, Gdk.KEY_Return, 0, no_modifier) is True and sent == [True]
    assert entry._on_key_pressed(None, Gdk.KEY_KP_Enter, 0, no_modifier) is True and len(sent) == 2
    assert entry._on_key_pressed(None, Gdk.KEY_Return, 0, shift) is False and len(sent) == 2
    assert entry._on_key_pressed(None, Gdk.KEY_a, 0, no_modifier) is False


def test_multi_line_text_round_trips_and_the_placeholder_follows_the_content():
    entry, _ = make_entry()
    assert entry._placeholder.get_visible()
    entry.set_text("line one\n\n- item\n```\ncode\n```")
    assert entry.get_text() == "line one\n\n- item\n```\ncode\n```" and not entry._placeholder.get_visible()
    entry.set_text("")
    assert entry._placeholder.get_visible() and entry.get_text() == ""


def test_the_entry_can_be_disabled():
    entry, _ = make_entry()
    entry.set_sensitive(False)
    assert not entry.get_sensitive()


# -- In the chat ---------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path):
    created = []

    def factory(**options):
        app, services, engine = build_app(tmp_path / f"md{len(created)}", **options)
        created.append((app, services))
        return app, services, engine

    yield factory
    for app, services in created:
        for window in list(app.get_windows()):
            window.destroy()
        services.worker.shutdown(timeout=1)
    Gtk.Widget.set_default_direction(Gtk.TextDirection.LTR)


def send(window, text):
    window._chat._entry.set_text(text)
    window._chat._on_send_clicked()
    pump(5, until=lambda: not window.is_busy)
    pump(0.3)


def test_a_markdown_answer_is_rendered_in_the_chat_and_stored_raw(make_app):
    app, services, _ = make_app(answer=MARKDOWN_ANSWER_EN)
    window = start(app, services)
    send(window, "What are the types of memory?")

    card = window._chat._messages.get_last_child()
    top = list(children(card._answer))
    assert "title-2" in top[0].get_css_classes() and len(top) >= 6
    assert card.text == MARKDOWN_ANSWER_EN
    assert services.store.turns(services.store.list_conversations()[0].id)[0].answer == MARKDOWN_ANSWER_EN


def test_multi_line_markdown_questions_reach_the_engine_unchanged_and_render_in_the_bubble(make_app):
    app, services, engine = make_app()
    window = start(app, services)
    question = "Explain these:\n\n- RAM\n- `SSD`"
    send(window, question)

    assert engine.asked[-1][0] == question
    bubble = window._chat._messages.get_first_child()
    bubble_view = next(w for w in descendants(bubble) if isinstance(w, MarkdownView))
    assert any(label.get_text() == "RAM" for label in labels(bubble_view))
    assert any(label.get_text() == "SSD" for label in labels(bubble_view))


def test_stored_markdown_answers_render_again_when_a_conversation_is_reopened(make_app):
    app, services, _ = make_app(answer=MARKDOWN_ANSWER_AR)
    window = start(app, services)
    send(window, "ما هي أنواع الذاكرة؟")
    conversation_id = window.current_conversation_id
    window.new_conversation()
    window._on_select_conversation(conversation_id)

    card = window._chat._messages.get_last_child()
    assert "title-2" in list(children(card._answer))[0].get_css_classes() and card.text == MARKDOWN_ANSWER_AR


def test_the_answer_language_preference_is_saved(make_app, tmp_path):
    from istinbat.gui.preferences import PreferencesDialog

    app, services, _ = make_app()
    window = start(app, services)
    dialog = PreferencesDialog(window)
    row = next(
        w for w in descendants(dialog.get_visible_page())
        if isinstance(w, Adw.ComboRow) and w.get_title() == translate("prefs.answer_language.title")
    )
    assert row.get_selected() == 0
    row.set_selected(2)
    assert services.settings.memory.answer_language is AnswerLanguage.ENGLISH
    assert '"answer_language": "en"' in (tmp_path / "md0" / "settings.json").read_text(encoding="utf-8")


def test_code_block_children_are_all_left_to_right_inside_right_to_left_text():
    view = view_for("```python\nx = 1\n```")
    frame = view.get_first_child()
    for widget in (frame, *children(frame), *(w for w in descendants(frame) if isinstance(w, Gtk.Label))):
        assert widget.get_direction() == Gtk.TextDirection.LTR


def test_a_table_does_not_stretch_beyond_its_content():
    grid = next(w for w in descendants(view_for("| a | b |\n|---|---|\n| 1 | 2 |")) if isinstance(w, Gtk.Grid))
    assert grid.get_halign() == Gtk.Align.START and grid.get_valign() == Gtk.Align.START
