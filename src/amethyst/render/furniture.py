"""What goes on a page besides the document: contents, running head, cover.

The two pipelines build this furniture in completely different ways — one in
CSS paged media, the other in Word sections and field codes — but they must
agree on *what* it says, or the same source comes out as two documents. The
decisions that both have to make identically are made once, here, and nowhere
else: which headings the contents lists, which heading level the running head
tracks, and what the cover has on it.

Nothing in this module knows about HTML or OOXML. It reads a parsed document
and returns the answers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from amethyst.document import Document, Heading

#: What a table of contents is called. Not read from the document, because it
#: is not in the document: it is furniture the renderer adds, and both formats
#: have to add it under the same name.
CONTENTS_HEADING = "Contents"

#: The heading levels a contents can list at all. ``--toc-depth`` cuts into
#: this; it cannot go past it, because ``h6`` is the last heading there is.
MAX_TOC_DEPTH = 6


@dataclass(frozen=True)
class Cover:
    """What a title page has on it, once the empty lines are taken out.

    A cover is worth making only if it has a title. Everything else is
    optional and simply absent when the frontmatter did not declare it.
    """

    title: str
    subtitle: str | None = None
    author: str | None = None
    date: str | None = None


def contents(document: Document, depth: int) -> list[Heading]:
    """The headings a table of contents lists, in document order.

    Deeper headings are dropped rather than flattened: a contents that lists
    every ``h6`` in a long document is a second document, not a way into the
    first.
    """
    return [item for item in document.headings if item.level <= depth]


def section_level(document: Document) -> int | None:
    """Which heading level the running head should name, if any.

    A running head is useful when it changes — it tells a reader which part of
    the document the page in their hand belongs to. So it tracks the shallowest
    level that occurs more than once, which for the ordinary shape of a
    Markdown file (one ``h1`` naming the document, ``h2`` sections under it)
    is the ``h2``.

    ``None`` when no level repeats: there is nothing to track, and a head that
    names the one heading in the document is just the title written twice.
    """
    counts = Counter(item.level for item in document.headings)
    for level in sorted(counts):
        if counts[level] > 1:
            return level
    return None


def cover(document: Document) -> Cover | None:
    """The title page's content, or ``None`` if there is not enough for one.

    Without a title there is no cover worth printing — a page carrying nothing
    but an author's name is a blank page with a mistake on it — so this
    returns nothing and the caller says so rather than emitting one.
    """
    title = document.title
    if not title:
        return None
    return Cover(
        title=title,
        subtitle=document.subtitle,
        author=document.author,
        date=document.date,
    )


def outline_depth(headings: Sequence[Heading], depth: int) -> int:
    """The deepest level actually present in a contents, for Word's ``TOC``.

    Word's field takes a range of heading levels rather than a list, and a
    range reaching past the deepest heading in the document is not wrong, only
    untidy. One is the floor: ``TOC \\o "1-0"`` is not a range.
    """
    present = [item.level for item in headings if item.level <= depth]
    return max(present, default=1)


__all__ = [
    "CONTENTS_HEADING",
    "MAX_TOC_DEPTH",
    "Cover",
    "contents",
    "cover",
    "outline_depth",
    "section_level",
]
