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


def page_css(theme: Theme, *, page_numbers: bool = True) -> str:
    """The paged-media block: sheet size, margins and the page number."""
    lines = [
        "@page {",
        f"  size: {theme.page.size};",
        f"  margin: {theme.page.margin};",
    ]
    if page_numbers:
        lines += [
            "  @bottom-center {",
            "    content: counter(page);",
            f"    font-family: {font_stack(theme.fonts.body)};",
            f"    font-size: {points(theme.type.small)};",
            f"    color: {theme.colors.muted};",
            "  }",
        ]
    lines += ["}", ""]
    return "\n".join(lines)


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


__all__ = ["font_stack", "multiple", "number", "page_css", "points", "root_css"]
