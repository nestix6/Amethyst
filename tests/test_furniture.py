"""The decisions both formats have to make identically.

Everything here is a pure function of a parsed document, which is the point of
the module: a contents that listed different headings in the PDF and in the
Word file, or a running head that named a different level in each, would be the
exact drift the shared theme exists to prevent — and neither would be visible
in a test of one format on its own.
"""

from __future__ import annotations

from amethyst.document import Document
from amethyst.render.furniture import (
    contents,
    cover,
    outline_depth,
    section_level,
)


def parse(text: str) -> Document:
    return Document.from_markdown(text)


# --- the contents ---------------------------------------------------------


def test_the_contents_lists_headings_in_document_order():
    document = parse("# One\n\n## Two\n\n# Three\n")
    assert [(item.level, item.text) for item in contents(document, 3)] == [
        (1, "One"),
        (2, "Two"),
        (1, "Three"),
    ]


def test_the_depth_cuts_the_contents_rather_than_flattening_it():
    document = parse("# One\n\n## Two\n\n### Three\n\n#### Four\n")
    assert [item.text for item in contents(document, 2)] == ["One", "Two"]
    assert [item.text for item in contents(document, 1)] == ["One"]


def test_every_entry_carries_the_anchor_its_heading_was_given():
    document = parse("## Inline formatting\n")
    assert [item.anchor for item in contents(document, 3)] == ["inline-formatting"]


def test_a_document_with_no_headings_has_nothing_to_list():
    assert contents(parse("Body text.\n"), 3) == []


def test_the_outline_range_stops_at_the_deepest_heading_there_is():
    """Word takes a range, and one reaching past the document is untidy."""
    document = parse("# One\n\n## Two\n")
    assert outline_depth(contents(document, 3), 3) == 2
    assert outline_depth(contents(document, 1), 1) == 1
    # Never zero: `TOC \\o "1-0"` is not a range.
    assert outline_depth([], 3) == 1


# --- the running head -----------------------------------------------------


def test_the_head_tracks_the_shallowest_level_that_repeats():
    """The ordinary shape: one h1 naming the document, h2 sections under it."""
    document = parse("# Doc\n\n## One\n\n## Two\n\n### Deeper\n")
    assert section_level(document) == 2


def test_a_document_of_chapters_tracks_its_chapters():
    assert section_level(parse("# One\n\n## a\n\n# Two\n")) == 1


def test_nothing_is_tracked_when_no_level_repeats():
    """A head naming the one heading in the document is the title, twice."""
    assert section_level(parse("# Only\n\n## Just the one\n")) is None
    assert section_level(parse("Body text.\n")) is None


# --- the cover ------------------------------------------------------------


def test_the_cover_is_built_from_the_frontmatter():
    document = parse(
        "---\ntitle: T\nsubtitle: S\nauthor: A\ndate: 2026-01-02\n---\n\nBody.\n"
    )
    page = cover(document)
    assert page is not None
    assert (page.title, page.subtitle, page.author, page.date) == (
        "T",
        "S",
        "A",
        "2026-01-02",
    )


def test_a_cover_falls_back_to_the_first_heading_for_its_title():
    page = cover(parse("# From the heading\n"))
    assert page is not None and page.title == "From the heading"


def test_there_is_no_cover_without_a_title():
    """A page carrying only an author is a blank page with a mistake on it."""
    assert cover(parse("---\nauthor: A\n---\n\nBody.\n")) is None
