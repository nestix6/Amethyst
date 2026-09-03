"""Renderers: one parsed document in, one format's bytes out.

Each format gets its own pipeline rather than a shared abstraction over both.
PDF goes through HTML and CSS, because CSS paged media already solves page
geometry, running furniture and bookmarks; Word has no equivalent and needs the
token stream walked directly. What keeps the two outputs recognisably the same
document is the theme they share, not a common renderer.
"""

from __future__ import annotations

from amethyst.render.base import Renderer, RenderOptions, RenderResult, Warn
from amethyst.render.docx import render_docx
from amethyst.render.html import render_html
from amethyst.render.pdf import render_pdf

__all__ = [
    "RenderOptions",
    "RenderResult",
    "Renderer",
    "Warn",
    "render_docx",
    "render_html",
    "render_pdf",
]
