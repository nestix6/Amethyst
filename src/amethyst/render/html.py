"""Tokens to one standalone HTML document — the PDF pipeline's first half.

Standalone on purpose. Everything the page needs is inlined, so the result can
be written out and opened in a browser, which is by far the fastest way to tell
a CSS mistake apart from a WeasyPrint limitation. It is also what an eventual
HTML output would emit, which is why this is its own module rather than a
private helper inside the PDF renderer.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from amethyst.document import Document
from amethyst.errors import RenderError
from amethyst.parse import build_parser
from amethyst.render.base import RenderOptions

#: The footer's own styling, spelled out rather than taken from a custom
#: property: a page margin box sits outside the document tree, so it inherits
#: nothing from :root. The theme layer will emit these from its own values.
FOOTER_FONT = '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif'
FOOTER_SIZE = "9pt"
FOOTER_COLOR = "#5d5a66"

#: Shown in the PDF's title bar when the document declares nothing better.
FALLBACK_TITLE = "Untitled"


def render_html(document: Document, options: RenderOptions) -> str:
    """Render the document as one self-contained HTML page."""
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html><head><meta charset="utf-8">',
            f"<title>{escape(document.title or FALLBACK_TITLE)}</title>",
            *(f"<style>\n{sheet}</style>" for sheet in stylesheets(options)),
            "</head>",
            "<body>",
            render_body(document),
            "</body></html>",
            "",
        ]
    )


def render_body(document: Document) -> str:
    """Render just the token stream, with no page around it.

    The parser is rebuilt rather than kept on the document because its options
    — ``xhtmlOut``, the ``language-`` class prefix — are part of how the tokens
    are meant to be written out, and they belong with the one function that
    declares them.
    """
    md = build_parser()
    # The environment the frontmatter and footnote plugins filled during
    # parsing is not needed to render: the only thing the render rules read
    # from it is an optional id prefix for footnote anchors, which a
    # single-document pipeline has no use for.
    return md.renderer.render(document.tokens, md.options, {}).rstrip("\n")


def stylesheets(options: RenderOptions) -> list[str]:
    """The stylesheets to inline, in cascade order — last one wins."""
    from amethyst.theme import base_css

    sheets = [base_css(), page_css(options)]
    if options.extra_css is not None:
        sheets.append(read_css(options.extra_css))
    return sheets


def page_css(options: RenderOptions) -> str:
    """The paged-media block: sheet size, margins and the page number.

    Generated rather than written into ``base.css`` because two of the three
    come from flags, and because ``size`` is an at-rule descriptor — it cannot
    read a custom property the way an ordinary declaration can.
    """
    lines = ["@page {", f"  size: {options.page_size};", f"  margin: {options.margin};"]
    if options.page_numbers:
        lines += [
            "  @bottom-center {",
            "    content: counter(page);",
            f"    font-family: {FOOTER_FONT};",
            f"    font-size: {FOOTER_SIZE};",
            f"    color: {FOOTER_COLOR};",
            "  }",
        ]
    lines += ["}", ""]
    return "\n".join(lines)


def read_css(path: Path) -> str:
    """Read a user's extra stylesheet, reporting a failure as one clear line."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or "it is not valid UTF-8 text"
        raise RenderError(
            f"Could not read the CSS at {path}: {detail.lower()}."
        ) from exc
