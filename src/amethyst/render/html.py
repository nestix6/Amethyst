"""Tokens to one standalone HTML document — the PDF pipeline's first half.

Standalone on purpose. Everything the page needs is inlined, so the result can
be written out and opened in a browser, which is by far the fastest way to tell
a CSS mistake apart from a WeasyPrint limitation. It is also what an eventual
HTML output would emit, which is why this is its own module rather than a
private helper inside the PDF renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any, cast

from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

from amethyst.document import Document
from amethyst.errors import RenderError
from amethyst.parse import build_parser
from amethyst.render.base import RenderOptions
from amethyst.render.furniture import (
    CONTENTS_HEADING,
    contents,
    cover,
    section_level,
)
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
            *meta_tags(document),
            *(f"<style>\n{sheet}</style>" for sheet in stylesheets(document, options)),
            "</head>",
            "<body>",
            *front_matter(document, options),
            render_body(document),
            "</body></html>",
            "",
        ]
    )


def meta_tags(document: Document) -> list[str]:
    """The frontmatter, as the tags WeasyPrint turns into PDF metadata.

    The same four fields the Word renderer writes into its core properties, so
    that a reader looking at the document's information pane sees the same
    thing whichever format they were sent. The date is written only when it is
    a real one: ``dcterms.created`` is a timestamp, and a document dated
    "Spring 2026" has a date for its title page and none for its metadata.
    """
    declared = [
        ("author", document.author),
        ("description", document.subtitle),
        ("keywords", document.keywords),
        ("dcterms.created", document.created.isoformat() if document.created else None),
    ]
    return [
        f'<meta name="{name}" content="{escape(value, quote=True)}">'
        for name, value in declared
        if value
    ]


def front_matter(document: Document, options: RenderOptions) -> list[str]:
    """The cover and the contents, in the order they are read."""
    pages = []
    if options.title_page:
        pages += title_page_html(document, options)
    if options.toc:
        pages += contents_html(document, options)
    return pages


def title_page_html(document: Document, options: RenderOptions) -> list[str]:
    """A cover built from the frontmatter, or nothing when there is no title."""
    page = cover(document)
    if page is None:
        options.warn(
            "--title-page needs a title; the document declares none, so no "
            "title page was made."
        )
        return []
    lines = ['<section class="title-page">']
    for css_class, value in (
        ("doc-title", page.title),
        ("doc-subtitle", page.subtitle),
        ("doc-author", page.author),
        ("doc-date", page.date),
    ):
        if value:
            lines.append(f'<p class="{css_class}">{escape(value)}</p>')
    lines.append("</section>")
    return lines


def contents_html(document: Document, options: RenderOptions) -> list[str]:
    """The table of contents, with the page numbers left for the PDF stage.

    Every entry is written as a link, and the dots and the page number are
    added by the stylesheet through ``target-counter`` — which only resolves
    once the document has been laid out, so there is nothing to count here.
    """
    entries = contents(document, options.toc_depth)
    if not entries:
        options.warn(
            "--toc needs headings; the document has none, so no contents was made."
        )
        return []
    lines = [
        '<nav class="contents">',
        f'<h1 class="toc-heading">{CONTENTS_HEADING}</h1>',
        "<ol>",
    ]
    for entry in entries:
        label = escape(entry.text)
        # An entry with no anchor cannot be linked, and so cannot carry a page
        # number either — target-counter has nothing to resolve. Listing it
        # unlinked beats dropping a heading out of the contents silently.
        body = (
            f'<a href="#{escape(entry.anchor, quote=True)}">{label}</a>'
            if entry.anchor
            else label
        )
        lines.append(f'<li class="toc-{entry.level}">{body}</li>')
    lines += ["</ol>", "</nav>"]
    return lines


def render_body(document: Document) -> str:
    """Render just the token stream, with no page around it.

    The parser is rebuilt rather than kept on the document because its options
    — ``xhtmlOut``, the ``language-`` class prefix — are part of how the tokens
    are meant to be written out, and they belong with the one function that
    declares them.
    """
    md = build_parser()
    # The parser's renderer is the HTML one, which the protocol the attribute
    # is typed as does not say; the rules table is on the concrete class.
    renderer = cast(RendererHTML, md.renderer)
    # markdown-it types its rules table as holding bound methods, which a
    # replacement rule is not and never was; the table itself takes any
    # callable of the right shape.
    rules: dict[str, Any] = renderer.rules
    rules["ordered_list_open"] = _ordered_list_rule(renderer)
    # The environment the frontmatter and footnote plugins filled during
    # parsing is not needed to render: the only thing the render rules read
    # from it is an optional id prefix for footnote anchors, which a
    # single-document pipeline has no use for.
    return renderer.render(document.tokens, md.options, {}).rstrip("\n")


def _ordered_list_rule(renderer: RendererHTML) -> Callable[..., str]:
    """Make a list start where the author said, rather than always at one.

    ``4. four`` opens a list numbered from four, and markdown-it writes that
    out as ``<ol start="4">`` — which WeasyPrint 69 does not read. Verified
    against WeasyPrint on its own, with none of Amethyst's CSS loaded, so it
    is the renderer and not the stylesheet. Setting the list-item counter
    directly does work, and is what this adds.

    The attribute is put on for the length of one call and taken off again:
    the token stream belongs to the document, which the Word renderer walks
    afterwards and has no use for a CSS declaration.
    """

    def ordered_list_open(
        tokens: list[Token],
        index: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[index]
        start = token.attrGet("start")
        if start is None:
            rendered: str = renderer.renderToken(tokens, index, options, env)
            return rendered
        token.attrSet("style", f"counter-reset: list-item {int(start) - 1}")
        try:
            rendered = renderer.renderToken(tokens, index, options, env)
        finally:
            token.attrs.pop("style", None)
        return rendered

    return ordered_list_open


def stylesheets(document: Document, options: RenderOptions) -> list[str]:
    """The stylesheets to inline, in cascade order — last one wins.

    The theme goes after the structural sheet rather than before it: both
    declare ``:root``, both at the same specificity, so the one that wins is
    simply the one that comes second.
    """
    sheets = [
        base_css(),
        root_css(options.theme),
        page_css(
            options.theme,
            page_numbers=options.page_numbers,
            running_title=document.title,
            running_section=section_level(document),
            front_matter=options.title_page or options.toc,
            title_page=options.title_page,
        ),
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
