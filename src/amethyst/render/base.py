"""What a renderer is: one document and some options in, one file's bytes out.

The protocol is deliberately narrow. HTML and EPUB are out of scope for v1 but
are the obvious next outputs, and keeping the contract to "bytes, plus whatever
is worth saying about them" is what makes adding one additive rather than a
change to everything that calls a renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from amethyst.document import Document
from amethyst.theme import Theme, default_theme

#: How a renderer reports something the user should know but that is not fatal
#: — an image it could not load, a construct it had to approximate. Renderers
#: are given this rather than printing, so nothing in this package has an
#: opinion about where output goes or whether --quiet was passed.
Warn = Callable[[str], None]

#: The Pygments style a document is highlighted with when the user names none.
#: It lives here rather than with the highlighter because it is the default of
#: an option declared below, and :mod:`amethyst.render.highlight` reads it back
#: from here so that there is one spelling of it.
DEFAULT_HIGHLIGHT_STYLE = "default"


def discard(message: str) -> None:
    """The default warning sink, for callers that do not want to hear it."""


@dataclass(frozen=True)
class RenderOptions:
    """Everything a renderer needs that is not part of the document itself.

    These are already resolved: the CLI has merged flags over defaults, so a
    renderer never has to reason about what was and was not passed. Page
    geometry is part of the theme rather than a field here — a flag that
    overrides it does so by handing over an overridden theme, which leaves one
    place for a renderer to read the sheet size from.
    """

    theme: Theme = field(default_factory=default_theme)
    #: Extra stylesheet, appended after everything else so it wins. PDF only.
    extra_css: Path | None = None
    page_numbers: bool = True
    #: Whether to open the document with a table of contents, and how deep to
    #: take it. The depth is carried even when the contents is off, so that
    #: nothing has to reason about which of the two flags was passed.
    toc: bool = False
    toc_depth: int = 3
    #: Whether to open the document with a title page built from frontmatter.
    title_page: bool = False
    #: The Pygments style code is coloured with, or ``"none"`` for no colour.
    #: Held as a name rather than as a built highlighter because a renderer
    #: needs one of its own anyway: a highlighter remembers what it has already
    #: warned about, and that is per conversion.
    highlight_style: str = DEFAULT_HIGHLIGHT_STYLE
    warn: Warn = discard


@dataclass(frozen=True)
class RenderResult:
    """The finished document, and what is worth telling the user about it."""

    data: bytes
    #: Page count, where the format has one. DOCX does not — Word decides
    #: pagination when it opens the file, so there is nothing honest to report.
    pages: int | None = None


class Renderer(Protocol):
    """One output format.

    A callable protocol rather than a class, because a renderer has no state
    worth keeping between documents; ``render_pdf`` satisfies it as written.
    """

    def __call__(self, document: Document, options: RenderOptions) -> RenderResult:
        """Turn ``document`` into the bytes of one file."""
        ...
