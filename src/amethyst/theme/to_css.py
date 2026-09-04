"""A theme, compiled to CSS: the custom properties, and the page block.

Two blocks come out of here, and they are separate for a reason.

The first is nothing but custom properties. It is appended after ``base.css``
so that it wins the cascade, and it declares no rules of its own — which is
what keeps the question of *how* a document is laid out in one file, and the
question of what it is made of in the theme.

The second is ``@page``, which cannot be done that way. ``size`` and ``margin``
are at-rule descriptors, so ``size: var(--page-size)`` does not resolve; and a
margin box sits outside the document tree, inheriting nothing from ``:root``,
so the page number's own font and colour have to be written out in full.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from amethyst.theme import Theme

#: A family name that needs no quotes: a bare word, which covers the generic
#: families — quoting ``serif`` would turn it into a search for a font called
#: "serif" — and the single-word brands. Everything else is quoted.
BARE_FAMILY = re.compile(r"\A[A-Za-z][A-Za-z0-9-]*\Z")


def root_css(theme: Theme) -> str:
    """The custom properties ``base.css`` reads, as one ``:root`` block."""
    type_ = theme.type
    declarations: list[tuple[str, str]] = [
        ("font-body", font_stack(theme.fonts.body)),
        ("font-heading", font_stack(theme.fonts.heading)),
        ("font-mono", font_stack(theme.fonts.mono)),
        ("", ""),
        ("size-body", points(type_.size)),
        ("size-small", points(type_.small)),
        ("size-code", multiple(type_.code)),
        ("size-title", multiple(type_.title)),
        ("leading", number(type_.line_height)),
        ("weight-heading", str(type_.heading_weight)),
        ("", ""),
        *(
            (f"size-h{level}", multiple(size))
            for level, size in enumerate(type_.headings, start=1)
        ),
        ("", ""),
        ("color-text", theme.colors.text),
        ("color-muted", theme.colors.muted),
        ("color-accent", theme.colors.accent),
        ("color-rule", theme.colors.rule),
        ("color-fill", theme.colors.fill),
        ("", ""),
        ("block-gap", multiple(theme.spacing.block)),
        ("indent", multiple(theme.spacing.indent)),
    ]
    body = [f"  --{name}: {value};" if name else "" for name, value in declarations]
    return "\n".join([f"/* theme: {theme.name} */", ":root {", *body, "}", ""])


def page_css(
    theme: Theme,
    *,
    page_numbers: bool = True,
    running_title: str | None = None,
    running_section: int | None = None,
    front_matter: bool = False,
    title_page: bool = False,
) -> str:
    """The paged-media block: sheet, margins, page number and running head.

    Everything here is generated rather than written in ``base.css`` because
    it depends on the document as well as the theme — the title is literal
    text, and which heading level feeds the running head is decided by
    counting the document's headings.

    ``running_title`` goes in the top-left corner as a literal string; it is
    not a named string set from the ``h1``, because a document whose body
    opens with an ``h1`` of its own would then have the head change halfway
    down. ``running_section`` is the heading level that feeds the top-right
    corner, and it *is* a named string, because that one is meant to change.
    """
    furniture = [
        f"    font-family: {font_stack(theme.fonts.body)};",
        f"    font-size: {points(theme.type.small)};",
        f"    color: {theme.colors.muted};",
    ]
    lines = [
        "@page {",
        f"  size: {theme.page.size};",
        f"  margin: {theme.page.margin};",
    ]
    if running_title:
        lines += [
            "  @top-left {",
            f"    content: {css_string(running_title)};",
            *furniture,
            "  }",
        ]
    if running_section is not None:
        lines += ["  @top-right {", "    content: string(section);", *furniture, "  }"]
    if page_numbers:
        lines += [
            "  @bottom-center {",
            "    content: counter(page);",
            *furniture,
            "  }",
        ]
    lines += ["}", ""]

    if running_title or running_section is not None:
        # The opening page of a document needs no running head: whatever it
        # would name is set in full a few centimetres below it.
        lines += [f"@page :first {{{_no_head(running_title, running_section)} }}", ""]
    if running_section is not None:
        lines += [f"h{running_section} {{ string-set: section content(); }}", ""]

    if front_matter:
        # Front matter belongs to no section and is not the document yet, so
        # it carries no head — and a cover carries no page number either.
        lines += [f"@page front {{{_no_head(running_title, running_section)} }}", ""]
        if title_page:
            lines += ["@page front:first { @bottom-center { content: none } }", ""]
    return "\n".join(lines)


def _no_head(running_title: str | None, running_section: int | None) -> str:
    """Empty out whichever margin boxes the running head was put in."""
    boxes = []
    if running_title:
        boxes.append(" @top-left { content: none }")
    if running_section is not None:
        boxes.append(" @top-right { content: none }")
    return "".join(boxes)


def css_string(value: str) -> str:
    """Quote arbitrary text as a CSS string, so a quote in a title is safe.

    The title reaches the stylesheet as a literal because a margin box cannot
    read a custom property. It is the author's text, though, so it has to be
    escaped rather than trusted: an unescaped quote would end the string and
    the rest of the block would be read as something else entirely.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    # A newline cannot appear inside a CSS string at all, escaped or not.
    escaped = " ".join(escaped.split())
    return f'"{escaped}"'


def font_stack(families: Sequence[str]) -> str:
    """Join family names into a CSS font stack, quoting only what needs it."""
    return ", ".join(
        family if BARE_FAMILY.match(family) else f'"{family}"' for family in families
    )


def points(value: float) -> str:
    """An absolute size, in the unit print is measured in."""
    return f"{number(value)}pt"


def multiple(value: float) -> str:
    """A size relative to the text it sits in."""
    return f"{number(value)}em"


def number(value: float) -> str:
    """Write a number the short way: 11 rather than 11.0, 1.45 as it is."""
    return f"{value:g}"


__all__ = [
    "css_string",
    "font_stack",
    "multiple",
    "number",
    "page_css",
    "points",
    "root_css",
]
