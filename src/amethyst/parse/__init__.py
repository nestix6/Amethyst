"""The parse layer: Markdown text in, a token stream and metadata out.

Nothing here knows about PDF or DOCX. :mod:`amethyst.document` assembles these
pieces into the ``Document`` the renderers are handed.
"""

from __future__ import annotations

from amethyst.parse.assets import Asset, AssetKind, resolve_assets
from amethyst.parse.frontmatter import parse_frontmatter, split_frontmatter
from amethyst.parse.markdown import build_parser

__all__ = [
    "Asset",
    "AssetKind",
    "build_parser",
    "parse_frontmatter",
    "resolve_assets",
    "split_frontmatter",
]
