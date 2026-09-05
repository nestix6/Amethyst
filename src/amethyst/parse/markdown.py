"""Construction of the parser both pipelines share.

One configuration serves both: the PDF path renders these tokens to HTML, the
DOCX path walks them directly. Keeping the plugin set in a single function is
what stops the two outputs from disagreeing about what the Markdown meant.
"""

from __future__ import annotations

from collections.abc import Callable

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

#: What markdown-it hands a highlighter: the code, the language written after
#: the fence, and whatever else was on that line. Returning ``None`` — or
#: anything empty — leaves markdown-it to escape the code itself, which is
#: exactly what an unhighlightable block wants.
Highlight = Callable[[str, str, str], "str | None"]


def build_parser(highlight: Highlight | None = None) -> MarkdownIt:
    """Return the parser Amethyst uses for every document.

    The ``gfm-like`` preset brings tables, strikethrough and linkify. Linkify
    is not self-contained: it hard-requires ``linkify-it-py`` and raises at
    *render* time rather than import time when it is absent, which is why that
    package is a declared dependency rather than an optional extra.

    ``highlight`` is only read when the tokens are rendered to HTML, so parsing
    a document needs none: it is an option of the HTML renderer that markdown-it
    happens to keep on the parser.
    """
    md = MarkdownIt("gfm-like", {"highlight": highlight} if highlight else None)
    md.use(front_matter_plugin)
    md.use(footnote_plugin)
    md.use(deflist_plugin)
    md.use(tasklists_plugin)
    md.use(anchors_plugin, max_level=ANCHOR_MAX_LEVEL)
    return md
