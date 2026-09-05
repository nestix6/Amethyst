"""Syntax highlighting, and the one thing that matters about it here: that the
two formats are driven from the same lookup.

A Pygments style is turned into a colour, a weight and a slope per token class,
and both pipelines read that same model — the PDF as CSS rules, Word as run
formatting. So the tests worth having are the ones that would catch the two
drifting apart, and the ones that catch a style being applied where the
document did not ask for it.
"""

from __future__ import annotations

import pytest

from amethyst.errors import UsageError
from amethyst.render.highlight import (
    DEFAULT_HIGHLIGHT_STYLE,
    NO_HIGHLIGHTING,
    Highlighter,
    highlight_styles,
    resolve_highlight_style,
)

CODE = "def f(x):\n    return x\n"


# --- naming a style -------------------------------------------------------


def test_the_default_style_is_a_real_pygments_style():
    assert Highlighter().enabled
    assert DEFAULT_HIGHLIGHT_STYLE in highlight_styles()


def test_an_unknown_style_is_bad_usage_and_lists_the_real_ones():
    with pytest.raises(UsageError) as excinfo:
        resolve_highlight_style("solarised")
    assert excinfo.value.exit_code == 2
    assert "monokai" in (excinfo.value.hint or "")


def test_none_turns_highlighting_off_without_being_a_pygments_style():
    highlighter = Highlighter(NO_HIGHLIGHTING)
    assert not highlighter.enabled
    assert highlighter.html(CODE, "python") is None
    assert highlighter.spans(CODE, "python") is None
    assert highlighter.css() == ""
    assert NO_HIGHLIGHTING in highlight_styles()


# --- the two compilations agree -------------------------------------------


def test_a_keyword_is_the_same_colour_in_both_formats():
    """The one property worth asserting: neither format invents a palette."""
    highlighter = Highlighter("default")
    spans = highlighter.spans(CODE, "python")
    assert spans is not None
    keyword = next(span for span in spans if span.text == "def")
    assert keyword.color is not None
    assert f"color: {keyword.color};" in highlighter.css()
    assert f'<span class="k">{keyword.text}</span>' in (
        highlighter.html(CODE, "python") or ""
    )


def test_the_stylesheet_colours_only_inside_a_code_block():
    """A rule that escaped `pre` would repaint the prose around it."""
    for line in Highlighter("default").css().splitlines():
        assert not line.strip() or line.startswith(("/*", "pre")), line


def test_the_stylesheet_does_not_retypeset_the_block():
    """Pygments' own style defs set a line height; the theme owns that."""
    css = Highlighter("default").css()
    assert "line-height" not in css
    assert "linenos" not in css


# --- light and dark -------------------------------------------------------


def test_a_light_style_leaves_the_page_its_own_background():
    highlighter = Highlighter("default")
    assert highlighter.background is None
    assert highlighter.foreground is None
    assert "pre {" not in highlighter.css()


def test_a_dark_style_brings_its_own_background_and_text_colour():
    highlighter = Highlighter("monokai")
    assert highlighter.background == "#272822"
    assert highlighter.foreground is not None
    assert f"background: {highlighter.background};" in highlighter.css()


def test_a_dark_style_colours_even_the_tokens_it_gives_no_colour():
    """Otherwise plain text in a dark block is the theme's near-black on black."""
    spans = Highlighter("monokai").spans(CODE, "python")
    assert spans is not None
    assert all(span.color is not None for span in spans)


# --- what is and is not highlighted ---------------------------------------


def test_a_fence_with_no_language_is_left_alone():
    assert Highlighter().html(CODE, "") is None
    assert Highlighter().spans(CODE, "") is None


def test_an_unknown_language_warns_once_and_sets_the_code_plain():
    messages: list[str] = []
    highlighter = Highlighter(warn=messages.append)
    assert highlighter.html("x", "pseudocode") is None
    assert highlighter.html("y", "pseudocode") is None
    assert len(messages) == 1
    assert "pseudocode" in messages[0]


def test_adjacent_runs_of_one_colour_are_merged():
    """Word stores a run per span, and a lexer emits one per bracket."""
    spans = Highlighter().spans(CODE, "python")
    assert spans is not None
    colors = [span.color for span in spans]
    assert all(one != two for one, two in zip(colors, colors[1:], strict=False))


def test_the_newline_every_lexer_adds_is_dropped():
    """It would be a visible empty line at the bottom of the shaded box."""
    spans = Highlighter().spans(CODE, "python")
    assert spans is not None
    assert not spans[-1].text.endswith("\n")
    assert "".join(span.text for span in spans) == CODE.rstrip("\n")
