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
from amethyst.theme import base_css
from amethyst.theme.to_css import page_css, root_css

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
    """The stylesheets to inline, in cascade order — last one wins.

    The theme goes after the structural sheet rather than before it: both
    declare ``:root``, both at the same specificity, so the one that wins is
    simply the one that comes second.
    """
    sheets = [
        base_css(),
        root_css(options.theme),
        page_css(options.theme, page_numbers=options.page_numbers),
    ]
    if options.extra_css is not None:
        sheets.append(read_css(options.extra_css))
    return sheets


def read_css(path: Path) -> str:
    """Read a user's extra stylesheet, reporting a failure as one clear line."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or "it is not valid UTF-8 text"
        raise RenderError(
            f"Could not read the CSS at {path}: {detail.lower()}."
        ) from exc
