"""Renderers: one parsed document in, one format's bytes out.

Each format gets its own pipeline rather than a shared abstraction over both.
PDF goes through HTML and CSS, because CSS paged media already solves page
geometry, running furniture and bookmarks; Word has no equivalent and needs the
token stream walked directly. What keeps the two outputs recognisably the same
document is the theme they share, not a common renderer.
"""

from __future__ import annotations

from amethyst.render.base import (
    DEFAULT_HIGHLIGHT_STYLE,
    Renderer,
    RenderOptions,
    RenderResult,
    Warn,
)
from amethyst.render.docx import render_docx
from amethyst.render.highlight import (
    NO_HIGHLIGHTING,
    Highlighter,
    highlight_styles,
    resolve_highlight_style,
)
from amethyst.render.html import render_html
from amethyst.render.pdf import render_pdf

__all__ = [
    "DEFAULT_HIGHLIGHT_STYLE",
    "NO_HIGHLIGHTING",
    "Highlighter",
    "RenderOptions",
    "RenderResult",
    "Renderer",
    "Warn",
    "highlight_styles",
    "render_docx",
    "render_html",
    "render_pdf",
    "resolve_highlight_style",
]
