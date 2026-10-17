# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import re

import pytest

from istinbat.markdown import (
    CodeBlock,
    Heading,
    ListBlock,
    Paragraph,
    Quote,
    Rule,
    Table,
    escape_markup,
    is_safe_link,
    parse_markdown,
    plain_text,
)


def first(text):
    return parse_markdown(text)[0]


def test_headings_keep_their_level_and_inline_formatting():
    block = first("## Section **one**")
    assert isinstance(block, Heading) and block.level == 2
    assert block.markup == "Section <b>one</b>" and block.plain == "Section one"


def test_inline_styles_become_pango_markup():
    markup = first("*em* **strong** ~~gone~~ `code`").markup
    assert "<i>em</i>" in markup and "<b>strong</b>" in markup and "<s>gone</s>" in markup
    assert 'font_family="monospace"' in markup and ">code</span>" in markup


def test_user_text_is_escaped_so_it_cannot_inject_markup():
    paragraph = first("5 < 6 & 7 > 3 <span foreground='red'>x</span> `a<b`")
    assert "&lt;span foreground=" in paragraph.markup and "<span foreground" not in paragraph.markup
    assert "5 &lt; 6 &amp; 7 &gt; 3" in paragraph.markup and "a&lt;b" in paragraph.markup


def test_raw_html_is_shown_as_text_never_interpreted():
    assert "&lt;script&gt;" in first("<script>alert(1)</script>").markup
    assert "<div" not in first("<div>box</div>").markup.replace("&lt;div", "")


def test_single_newlines_are_kept_as_line_breaks():
    assert first("line one\nline two").markup == "line one\nline two"


def test_code_blocks_keep_their_language_and_content_verbatim():
    block = first("```python\nprint('<hi>')\n\nx = 1\n```")
    assert block == CodeBlock("print('<hi>')\n\nx = 1", "python")
    assert first("```\nplain\n```").language == ""
    assert first("    indented code").code == "indented code"


def test_bullet_and_ordered_lists_with_nesting_and_start_number():
    lists = parse_markdown("- a\n- b\n  - c\n\n3. x\n4. y")
    bullet, ordered = lists
    assert isinstance(bullet, ListBlock) and not bullet.ordered and len(bullet.items) == 2
    nested = bullet.items[1].blocks[1]
    assert isinstance(nested, ListBlock) and nested.items[0].blocks[0].plain == "c"
    assert ordered.ordered and ordered.start == 3 and len(ordered.items) == 2


def test_blockquotes_contain_blocks():
    block = first("> quoted *text*\n>\n> - item")
    assert isinstance(block, Quote)
    assert isinstance(block.blocks[0], Paragraph) and isinstance(block.blocks[1], ListBlock)


def test_tables_have_header_rows_and_column_alignment():
    block = first("| Name | Qty | Note |\n|:--|--:|:-:|\n| A | 1 | x |\n| B | 2 | y |")
    assert isinstance(block, Table)
    assert [cell.plain for cell in block.header] == ["Name", "Qty", "Note"]
    assert [cell.align for cell in block.header] == ["left", "right", "center"]
    assert [[cell.plain for cell in row] for row in block.rows] == [["A", "1", "x"], ["B", "2", "y"]]


def test_horizontal_rule():
    assert first("---") == Rule()


def test_safe_links_become_anchors_and_unsafe_ones_become_plain_text():
    assert '<a href="https://example.com/a?x=1&amp;y=2">site</a>' in first("[site](https://example.com/a?x=1&y=2)").markup
    for unsafe in ("javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", "ftp://host/file"):
        markup = first(f"[click]({unsafe})").markup
        assert "<a " not in markup and "click" in markup


def test_link_scheme_check_ignores_case_and_surrounding_spaces():
    assert is_safe_link(" HTTPS://example.com") and is_safe_link("mailto:a@b.c")
    assert not is_safe_link("javascript:alert(1)") and not is_safe_link("//example.com/x")


def test_images_are_replaced_by_their_alt_text():
    paragraph = first("![A diagram](https://example.com/d.png)")
    assert paragraph.markup == "<i>A diagram</i>" and "http" not in paragraph.markup


def test_arabic_and_mixed_text_survive_unchanged():
    block = first("**المعلومات** هي النتائج — Information is `data`.")
    assert "<b>المعلومات</b>" in block.markup and block.plain.startswith("المعلومات هي")


def test_plain_text_for_direction_skips_code_and_includes_nested_content():
    blocks = parse_markdown("```\ncode\n```\n\n- مرحبا\n\n> hello")
    assert plain_text(blocks[0]) == "" and plain_text(blocks[1]) == "مرحبا" and plain_text(blocks[2]) == "hello"


def test_empty_input_has_no_blocks():
    assert parse_markdown("") == [] and parse_markdown("   \n\n") == []


def test_unclosed_constructs_degrade_gracefully_while_streaming():
    for partial in ("**bold start", "```python\nprint(", "| a | b |\n|--", "- ", "[link](http://x", "1."):
        parse_markdown(partial)          # Must not raise: answers are rendered while they stream.


def test_escape_markup_handles_attribute_quotes():
    assert escape_markup('a"b\'c<&>') == "a\"b'c&lt;&amp;&gt;"
    assert escape_markup('a"b\'c', attribute=True) == "a&quot;b&#39;c"


def test_equal_blocks_compare_equal_so_views_can_reuse_widgets():
    assert parse_markdown("# T\n\ntext") == parse_markdown("# T\n\ntext")
    assert parse_markdown("# T\n\ntext")[0] == parse_markdown("# T\n\ntext more")[0]


@pytest.mark.parametrize("source", [
    "*a* **b** `c` ~~d~~ [e](https://x.y) ![f](u) 5<6 & \"q\" 'r'",
    "| h |\n|---|\n| <b> & |",
    "# t <&>\n\n> q & <\n\n- i < j",
])
def test_every_generated_markup_string_is_valid_pango(source):
    gi = pytest.importorskip("gi")
    gi.require_version("Pango", "1.0")
    from gi.repository import Pango

    def walk(blocks):
        for block in blocks:
            if isinstance(block, (Paragraph, Heading)):
                yield block.markup
            elif isinstance(block, Quote):
                yield from walk(block.blocks)
            elif isinstance(block, ListBlock):
                for item in block.items:
                    yield from walk(item.blocks)
            elif isinstance(block, Table):
                yield from (cell.markup for cell in (*block.header, *(c for row in block.rows for c in row)))

    for markup in walk(parse_markdown(source)):
        # <a> is a GtkLabel extension that Pango itself rejects; the GUI tests cover links.
        pango_only = re.sub(r"</?a\b[^>]*>", "", markup)
        Pango.parse_markup(pango_only, -1, "\0")      # Raises GLib.Error on invalid markup.
