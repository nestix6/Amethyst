"""Syntax highlighting, compiled the same two ways a theme is.

Pygments knows how to colour code and how to write the HTML for it. What it
does not know is that this project has two pipelines which must agree, so what
comes out of here is not Pygments' stylesheet but a small model of it: a
colour, a weight and a slope per token class. The PDF path turns that into CSS
rules and the Word path turns it into run formatting, from the same lookup, for
exactly the reason :mod:`amethyst.theme` compiles two ways rather than one.

Pygments' own ``get_style_defs`` is deliberately not used. It writes rules for
line numbering that nothing here emits, and a ``pre { line-height: 125% }``
that would quietly override the stylesheet's own leading — a highlighting style
is meant to colour the code, not to re-typeset it.

Two decisions are worth knowing about:

A **light style keeps the theme's background.** Code then sits on the same fill
as the inline code and the table headings around it, which is what makes a
highlighted block still look like part of the document. A **dark style brings
its own**, because it has to: its colours are chosen against a dark ground and
are unreadable on a light one.

**Nothing is guessed.** A fence with no language, or with one Pygments does not
recognise, is set plain rather than passed to a guesser. Guessing is slow, and
when it is wrong it is wrong in colour. Under a dark style such a block is
still a dark panel, in both formats — a light box beside a dark one, a
paragraph apart, is worse than an uncoloured one.

Inline code is never highlighted: three words between backticks name no
language, and there is nothing to lex. It keeps the theme's own fill even when
the blocks around it are dark, because it belongs to the sentence it sits in
rather than to a panel.
"""

from __future__ import annotations

from dataclasses import dataclass

from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name
from pygments.style import Style
from pygments.styles import get_all_styles, get_style_by_name
from pygments.token import STANDARD_TYPES, Token, _TokenType
from pygments.util import ClassNotFound

from amethyst.errors import UsageError
from amethyst.render.base import DEFAULT_HIGHLIGHT_STYLE, Warn, discard

#: What to pass to turn highlighting off. Not a Pygments style name — the point
#: is to have a spelling for "leave the code alone", and code set in the mono
#: face with no colour at all is a legitimate way to want a document to look.
NO_HIGHLIGHTING = "none"

#: Below this relative luminance a background counts as dark, and the style is
#: taken to have been designed against its own ground rather than the page's.
DARK_BELOW = 0.4

#: The plain-text colour for a dark style that names none, which no shipped
#: style does — a legible off-white rather than a guess at the style's intent.
FALLBACK_FOREGROUND = "#f8f8f2"


@dataclass(frozen=True)
class Span:
    """One run of code that is all one colour."""

    text: str
    color: str | None = None
    bold: bool = False
    italic: bool = False

    @property
    def plain(self) -> bool:
        """Whether this span asks for nothing the surrounding style lacks."""
        return self.color is None and not self.bold and not self.italic


class Highlighter:
    """One highlighting style, ready for either pipeline.

    Built per render rather than cached, because it remembers which unknown
    languages it has already complained about: a document that fences twenty
    blocks as ```pseudocode`` should say so once, not twenty times.
    """

    def __init__(self, style: str = DEFAULT_HIGHLIGHT_STYLE, *, warn: Warn = discard):
        self.name = resolve_highlight_style(style)
        self._warn = warn
        self._style: type[Style] | None = (
            None if self.name == NO_HIGHLIGHTING else get_style_by_name(self.name)
        )
        self._unknown: set[str] = set()

    @property
    def enabled(self) -> bool:
        """Whether this highlighter colours anything at all."""
        return self._style is not None

    @property
    def background(self) -> str | None:
        """The ground this style needs, or ``None`` to keep the theme's fill.

        Only a dark style answers with a colour. See the module docstring: a
        light style is an ornament on the page's own background, and a dark one
        is a panel that brings its own.
        """
        if self._style is None:
            return None
        declared = _hex(self._style.background_color)
        if declared is None or _luminance(declared) >= DARK_BELOW:
            return None
        return declared

    @property
    def foreground(self) -> str | None:
        """The plain-text colour that goes with :attr:`background`."""
        if self.background is None:
            return None
        assert self._style is not None
        declared = self._format(Token.Text).color
        return declared or FALLBACK_FOREGROUND

    def html(self, code: str, language: str) -> str | None:
        """The code as coloured ``<span>``s, or ``None`` to set it plain.

        No wrapper: markdown-it puts the result inside the ``<pre><code>`` it
        would have written anyway, so the stylesheet's idea of what a code
        block is stays in one place.
        """
        lexer = self._lexer(language)
        if lexer is None:
            return None
        formatter = HtmlFormatter(nowrap=True, style=self.name)
        return pygments_highlight(code, lexer, formatter).rstrip("\n")

    def spans(self, code: str, language: str) -> list[Span] | None:
        """The code as coloured runs, or ``None`` to set it plain.

        The Word side of :meth:`html`. Trailing newlines are dropped here
        rather than by the caller: every lexer appends one, and in Word a
        trailing newline is a visible empty line inside the shaded box.
        """
        lexer = self._lexer(language)
        if lexer is None:
            return None
        found: list[Span] = []
        for token, text in lexer.get_tokens(code):
            style = self._format(token)
            span = Span(
                text=text,
                color=style.color or self.foreground,
                bold=style.bold,
                italic=style.italic,
            )
            # A lexer emits a token per punctuation mark, and Word stores a run
            # per span; merging the ones that are formatted alike takes a
            # fenced block from hundreds of runs to a handful.
            if found and _alike(found[-1], span):
                found[-1] = Span(
                    text=found[-1].text + span.text,
                    color=span.color,
                    bold=span.bold,
                    italic=span.italic,
                )
            else:
                found.append(span)
        return _without_trailing_newline(found)

    def css(self) -> str:
        """The style as CSS rules, scoped to the code block they colour.

        Rules are emitted shallowest token type first. They all have the same
        specificity, so where Pygments gives a span more than one class it is
        the later rule — the more specific token — that has to win.
        """
        if self._style is None:
            return ""
        lines = [f"/* highlighting: {self.name} */"]
        background = self.background
        if background is not None:
            lines.append(
                f"pre {{ background: {background}; color: {self.foreground}; "
                f"border-color: {background}; }}"
            )
        for token, css_class in sorted(
            STANDARD_TYPES.items(), key=lambda item: len(item[0])
        ):
            if not css_class:
                continue
            declarations = _declarations(self._format(token))
            if declarations:
                lines.append(f"pre .{css_class} {{ {declarations} }}")
        return "\n".join([*lines, ""])

    def _lexer(self, language: str) -> Lexer | None:
        """The lexer for a fence's language, warning once when there is none."""
        if self._style is None or not language:
            return None
        try:
            return get_lexer_by_name(language)
        except ClassNotFound:
            if language not in self._unknown:
                self._unknown.add(language)
                self._warn(
                    f"no syntax highlighting for {language!r}; that code is set plain."
                )
            return None

    def _format(self, token: _TokenType) -> Span:
        """How this style sets one token type, with inheritance resolved."""
        assert self._style is not None
        declared = self._style.style_for_token(token)
        return Span(
            text="",
            color=_hex(declared["color"]),
            bold=declared["bold"],
            italic=declared["italic"],
        )


def resolve_highlight_style(name: str) -> str:
    """Check that a highlighting style exists, returning it as given.

    A name that is not a style is a mistyped invocation rather than a broken
    document, so it exits 2 like an unknown theme does — and the hint lists
    every style, because there is no other way to find out what they are
    called.
    """
    if name == NO_HIGHLIGHTING:
        return name
    try:
        get_style_by_name(name)
    except ClassNotFound:
        raise UsageError(
            f"Unknown highlighting style {name!r}.",
            hint=f"Styles: {', '.join(highlight_styles())}.",
        ) from None
    return name


def highlight_styles() -> tuple[str, ...]:
    """Every style that can be named, sorted, with ``none`` among them."""
    return tuple(sorted([*get_all_styles(), NO_HIGHLIGHTING]))


def _declarations(span: Span) -> str:
    """One token class's formatting, as the body of a CSS rule."""
    parts = []
    if span.color is not None:
        parts.append(f"color: {span.color};")
    if span.bold:
        parts.append("font-weight: 600;")
    if span.italic:
        parts.append("font-style: italic;")
    return " ".join(parts)


def _alike(one: Span, other: Span) -> bool:
    """Whether two spans are formatted identically, text aside."""
    return (one.color, one.bold, one.italic) == (other.color, other.bold, other.italic)


def _without_trailing_newline(spans: list[Span]) -> list[Span]:
    """Drop the newline every lexer adds, and any the author left behind."""
    while spans:
        trimmed = spans[-1].text.rstrip("\n")
        if trimmed:
            spans[-1] = Span(
                text=trimmed,
                color=spans[-1].color,
                bold=spans[-1].bold,
                italic=spans[-1].italic,
            )
            break
        spans.pop()
    return spans


def _hex(color: str | None) -> str | None:
    """A Pygments colour as CSS hex. It stores them without the ``#``.

    A style that declares no colour for a token gives ``None``, and one that
    declares no background gives ``""`` — both mean "say nothing here".
    """
    if not color:
        return None
    return color if color.startswith("#") else f"#{color}"


def _luminance(color: str) -> float:
    """Relative luminance of a hex colour, 0 for black and 1 for white.

    The sRGB coefficients, without the gamma expansion a contrast ratio would
    need: the only question being asked is "is this a dark panel or a light
    page", and that answer does not change between the two.
    """
    digits = color.lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) != 6:
        return 1.0
    red, green, blue = (int(digits[at : at + 2], 16) / 255 for at in (0, 2, 4))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


__all__ = [
    "DEFAULT_HIGHLIGHT_STYLE",
    "NO_HIGHLIGHTING",
    "Highlighter",
    "Span",
    "highlight_styles",
    "resolve_highlight_style",
]
