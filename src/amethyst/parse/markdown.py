"""Construction of the parser both pipelines share.

One configuration serves both: the PDF path renders these tokens to HTML, the
DOCX path walks them directly. Keeping the plugin set in a single function is
what stops the two outputs from disagreeing about what the Markdown meant.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

#: Deepest heading level that gets an ``id``. Anchors cost nothing and an
#: internal link can point at any heading, so every level gets one; --toc-depth
#: decides which of them reach the table of contents, separately and later.
ANCHOR_MAX_LEVEL = 6


def build_parser() -> MarkdownIt:
    """Return the parser Amethyst uses for every document.

    The ``gfm-like`` preset brings tables, strikethrough and linkify. Linkify
    is not self-contained: it hard-requires ``linkify-it-py`` and raises at
    *render* time rather than import time when it is absent, which is why that
    package is a declared dependency rather than an optional extra.
    """
    md = MarkdownIt("gfm-like")
    md.use(front_matter_plugin)
    md.use(footnote_plugin)
    md.use(deflist_plugin)
    md.use(tasklists_plugin)
    md.use(anchors_plugin, max_level=ANCHOR_MAX_LEVEL)
    return md
