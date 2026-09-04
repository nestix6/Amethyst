"""A theme, compiled to Word styles — the other half of ``to_css``.

The same declaration of fonts, sizes, colour and page geometry comes out here
as a set of style definitions on a ``python-docx`` document, so that the Word
file and the PDF are the same document rather than two documents that happen
to share a source. Nothing in the Word renderer names a font or a colour, for
the same reason nothing in the PDF renderer does.

Three things are worth knowing before changing anything here.

Word's built-in styles are not neutral. ``Heading 1`` arrives bound to the
document theme's major font and to ``accent1``, and those bindings are written
as *separate attributes* that win over the plain ones — so setting a font name
is not enough, the theme binding has to be taken off as well.

Only three levels of list style exist (``List Bullet`` … ``List Bullet 3``),
so deeper nesting has to be clamped rather than continued.

And this module reaches into :mod:`amethyst.ooxml` for shading and
borders, which is the one place the theme layer looks at the render layer.
Word styles are XML, so a compiler that targets them needs the same handful of
elements the renderer does, and the alternative — a second copy of ``w:shd``
— is worse than the import.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml.ns import qn
from docx.shared import Emu, Length, Pt, RGBColor

from amethyst.ooxml import clear_properties_child, set_borders, shade
from amethyst.theme import Theme

#: Paragraph and character styles Amethyst defines because Word has nothing
#: close enough. Prefixed so they are recognisable in Word's style pane and
#: cannot collide with a built-in.
CODE_STYLE = "Amethyst Code"
CODE_INLINE_STYLE = "Amethyst Code Inline"
TABLE_TEXT_STYLE = "Amethyst Table Text"
FOOTNOTE_STYLE = "Amethyst Footnote"
COVER_DATE_STYLE = "Amethyst Cover Date"

#: Built-in styles the theme restyles rather than replaces. A Word user who
#: knows these names should find them doing what the names say.
BODY_STYLE = "Normal"
QUOTE_STYLE = "Quote"
FOOTER_STYLE = "Footer"
HEADER_STYLE = "Header"
LINK_STYLE = "Hyperlink"
TABLE_STYLE = "Table Grid"
TITLE_STYLE = "Title"
SUBTITLE_STYLE = "Subtitle"
TOC_HEADING_STYLE = "TOC Heading"

HEADING_STYLES = tuple(f"Heading {level}" for level in range(1, 7))

#: Contents entries, one style per heading level. Word writes these itself
#: when it refreshes the field, so they exist to be found rather than to be
#: chosen: a refreshed contents comes back styled by the theme and not by
#: Word's factory defaults.
TOC_STYLES = tuple(f"TOC {level}" for level in range(1, 7))

#: List styles, outermost level first. Word defines three and no more, so the
#: fourth level of nesting and everything under it reuses the third.
BULLET_STYLES = ("List Bullet", "List Bullet 2", "List Bullet 3")
NUMBER_STYLES = ("List Number", "List Number 2", "List Number 3")

#: How far each level of the built-in list styles is indented. Written down
#: because block content inside a list item — a code block under a bullet —
#: has to line up with the text of the item it belongs to, and no style says
#: so on its behalf.
LIST_INDENT_STEP = Pt(18)

#: Generic CSS families, which name a category rather than a font. Word wants
#: an installed font, so these are skipped when the stack is reduced to the one
#: name a Word style can hold.
GENERIC_FAMILIES = {
    "serif": "Times New Roman",
    "sans-serif": "Arial",
    "monospace": "Courier New",
    "cursive": "Segoe Script",
    "fantasy": "Impact",
    "system-ui": "Calibri",
    "ui-serif": "Times New Roman",
    "ui-sans-serif": "Arial",
    "ui-monospace": "Courier New",
    "ui-rounded": "Arial",
    "math": "Cambria Math",
    "emoji": "Segoe UI Emoji",
}

#: Named sheet sizes in millimetres, portrait, as CSS paged media spells them.
NAMED_PAGE_SIZES = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "b4": (250.0, 353.0),
    "b5": (176.0, 250.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
    "ledger": (279.4, 431.8),
}

#: How many of each unit make an inch, which is the unit Word measures in.
UNITS_PER_INCH = {
    "in": 1.0,
    "cm": 2.54,
    "mm": 25.4,
    "q": 101.6,
    "pt": 72.0,
    "pc": 6.0,
    "px": 96.0,
}

EMU_PER_INCH = 914400

LENGTH = re.compile(r"\A([+-]?(?:\d+\.?\d*|\.\d+))([a-z]*)\Z")

#: What Word calls a font weight: there is only bold, so a theme's numeric
#: weight is a threshold rather than a value.
BOLD_AT = 600

#: Heading line height, and the gap above and below one, as multiples of the
#: body size. These mirror the structural stylesheet, which sets the same
#: relationships in CSS and is where they are explained.
HEADING_LEADING = 1.2
CODE_LEADING = 1.4
HEADING_SPACE_BEFORE = 1.4
HEADING_SPACE_AFTER = 0.5

#: The title page and the contents, in the same multiples of the body size the
#: stylesheet uses for them. Word cannot read a stylesheet and CSS cannot read
#: a Word style, so these are two copies of one decision — which is why they
#: are written here, beside the rest of that decision, rather than inline.
TITLE_LEADING = 1.15
TITLE_SPACE_AFTER = 0.3
SUBTITLE_LEADING = 1.3
SUBTITLE_SPACE_AFTER = 3.0
COVER_SPACE_AFTER = 0.15
#: How far down the sheet the title starts: ``.title-page { padding-top }``.
TITLE_PAGE_OFFSET = 8.0
#: One level of contents indent, and the gap under an entry.
TOC_INDENT = 1.2
TOC_SPACE_AFTER = 0.3
#: The air above a top-level contents entry, which groups the ones under it.
TOC_SPACE_BEFORE = 0.7

Warn = Callable[[str], None]


def _discard(message: str) -> None:
    """The warning sink for callers with nowhere to put a warning."""


def apply_theme(document: Any, theme: Theme, *, warn: Warn = _discard) -> None:
    """Restyle a fresh Word document to match a theme, page geometry included.

    Called once, on an empty document, before anything is written into it —
    everything after this reads a style by name and never sets a font.
    """
    _body(document, theme)
    _headings(document, theme)
    _lists(document, theme)
    _quote(document, theme)
    _code(document, theme)
    _tables(document, theme)
    _footnotes(document, theme)
    _links(document, theme)
    _running(document, theme)
    apply_page(document.sections[0], theme, warn=warn)
    # After the page, because a contents entry needs a tab stop at the right
    # edge of the text column and there is no column until the sheet is set.
    _cover(document, theme)
    _contents(document, theme)


# --- styles ---------------------------------------------------------------


def _body(document: Any, theme: Theme) -> None:
    style = document.styles[BODY_STYLE]
    _font(
        style, family(theme.fonts.body), size=theme.type.size, color=theme.colors.text
    )
    paragraph = style.paragraph_format
    paragraph.line_spacing = theme.type.line_height
    paragraph.space_before = Pt(0)
    paragraph.space_after = Pt(theme.type.size * theme.spacing.block)


def _headings(document: Any, theme: Theme) -> None:
    heading_font = family(theme.fonts.heading)
    for level, (name, scale) in enumerate(
        zip(HEADING_STYLES, theme.type.headings, strict=True), start=1
    ):
        style = document.styles[name]
        # The last level is set in the muted colour rather than the text one,
        # which is what the structural stylesheet does with h6: at body size
        # and body colour it would be indistinguishable from a bold paragraph.
        color = (
            theme.colors.muted if level == len(HEADING_STYLES) else theme.colors.text
        )
        _font(
            style,
            heading_font,
            size=theme.type.size * scale,
            color=color,
            bold=theme.type.heading_weight >= BOLD_AT,
            # Word's Heading 6 arrives italic, and the stylesheet's does not.
            italic=False,
        )
        paragraph = style.paragraph_format
        paragraph.line_spacing = HEADING_LEADING
        # A top-level heading opens a section and has nothing to be pushed
        # away from, so it alone starts flush.
        before = 0.0 if level == 1 else HEADING_SPACE_BEFORE
        paragraph.space_before = Pt(theme.type.size * before)
        paragraph.space_after = Pt(theme.type.size * HEADING_SPACE_AFTER)
        # A heading stranded at the foot of a page is the most visible
        # typesetting failure there is, and these are the two rules that fix it.
        paragraph.keep_with_next = True
        paragraph.keep_together = True


def _lists(document: Any, theme: Theme) -> None:
    """Tighten the list styles, which are otherwise as loose as a paragraph."""
    for name in (*BULLET_STYLES, *NUMBER_STYLES):
        paragraph = document.styles[name].paragraph_format
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(theme.type.size * 0.2)


def _quote(document: Any, theme: Theme) -> None:
    style = document.styles[QUOTE_STYLE]
    # Word's Quote is italic; the PDF's is not, and a blockquote holding a
    # paragraph of prose should not be set in italic for its whole length.
    _font(style, family(theme.fonts.body), color=theme.colors.muted, italic=False)
    paragraph = style.paragraph_format
    paragraph.left_indent = quote_indent(theme)
    paragraph.space_after = Pt(theme.type.size * theme.spacing.block)
    set_borders(
        style.element.get_or_add_pPr(),
        ["left"],
        color=theme.colors.rule,
        size=12,
        space=6,
    )


def _code(document: Any, theme: Theme) -> None:
    block = _new_style(document, CODE_STYLE, WD_STYLE_TYPE.PARAGRAPH)
    _font(
        block,
        family(theme.fonts.mono),
        size=theme.type.size * theme.type.code,
        color=theme.colors.text,
    )
    paragraph = block.paragraph_format
    paragraph.line_spacing = CODE_LEADING
    paragraph.space_before = Pt(0)
    paragraph.space_after = Pt(theme.type.size * theme.spacing.block)
    properties = block.element.get_or_add_pPr()
    shade(properties, theme.colors.fill)
    set_borders(
        properties, ["top", "left", "bottom", "right"], color=theme.colors.rule, space=6
    )

    inline = _new_style(document, CODE_INLINE_STYLE, WD_STYLE_TYPE.CHARACTER)
    _font(inline, family(theme.fonts.mono), size=theme.type.size * theme.type.code)
    shade(inline.element.get_or_add_rPr(), theme.colors.fill)


def _tables(document: Any, theme: Theme) -> None:
    """A cell sets a size smaller than the text around it, as the PDF does."""
    style = _new_style(document, TABLE_TEXT_STYLE, WD_STYLE_TYPE.PARAGRAPH)
    _font(
        style, family(theme.fonts.body), size=theme.type.small, color=theme.colors.text
    )
    paragraph = style.paragraph_format
    paragraph.space_before = Pt(0)
    paragraph.space_after = Pt(0)


def _footnotes(document: Any, theme: Theme) -> None:
    style = _new_style(document, FOOTNOTE_STYLE, WD_STYLE_TYPE.PARAGRAPH)
    _font(
        style, family(theme.fonts.body), size=theme.type.small, color=theme.colors.muted
    )
    paragraph = style.paragraph_format
    paragraph.space_before = Pt(0)
    paragraph.space_after = Pt(theme.type.size * 0.35)


def _links(document: Any, theme: Theme) -> None:
    # "Hyperlink" is a Word style name rather than one of ours, so it is
    # declared as built-in: Word applies it to a link the user types, and a
    # document with two spellings of the same idea in its style pane is worse
    # than one that reuses the name Word already knows.
    style = _new_style(document, LINK_STYLE, WD_STYLE_TYPE.CHARACTER, builtin=True)
    _font(style, color=theme.colors.accent)
    style.font.underline = False


def _running(document: Any, theme: Theme) -> None:
    """The head and the foot, which are the same small muted register."""
    for name in (HEADER_STYLE, FOOTER_STYLE):
        _font(
            document.styles[name],
            family(theme.fonts.body),
            size=theme.type.small,
            color=theme.colors.muted,
        )


def _cover(document: Any, theme: Theme) -> None:
    """Word's ``Title`` and ``Subtitle``, restyled into a title page.

    Both arrive bound to the document theme rather than to this one — the
    title is ruled off underneath in an accent colour that belongs to no theme
    here, and the subtitle is italic, coloured and, oddly, carries a numbering
    reference. All of that has to be taken off rather than overridden.
    """
    title = document.styles[TITLE_STYLE]
    _font(
        title,
        family(theme.fonts.heading),
        size=theme.type.size * theme.type.title,
        color=theme.colors.text,
        bold=theme.type.heading_weight >= BOLD_AT,
        italic=False,
    )
    properties = title.element.get_or_add_pPr()
    clear_properties_child(properties, "w:pBdr")
    title.paragraph_format.line_spacing = TITLE_LEADING
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(theme.type.size * TITLE_SPACE_AFTER)

    subtitle = document.styles[SUBTITLE_STYLE]
    _font(
        subtitle,
        family(theme.fonts.body),
        size=theme.type.size * theme.type.headings[2],
        color=theme.colors.muted,
        bold=False,
        italic=False,
    )
    clear_properties_child(subtitle.element.get_or_add_pPr(), "w:numPr")
    subtitle.paragraph_format.line_spacing = SUBTITLE_LEADING
    subtitle.paragraph_format.space_before = Pt(0)
    subtitle.paragraph_format.space_after = Pt(theme.type.size * SUBTITLE_SPACE_AFTER)

    date = _new_style(document, COVER_DATE_STYLE, WD_STYLE_TYPE.PARAGRAPH)
    _font(
        date, family(theme.fonts.body), size=theme.type.small, color=theme.colors.muted
    )
    date.paragraph_format.space_before = Pt(0)
    date.paragraph_format.space_after = Pt(0)


def _contents(document: Any, theme: Theme) -> None:
    """The contents entry styles, one per heading level.

    Each carries a right tab stop with a dotted leader at the edge of the text
    column, which is what turns "heading, tab, page number" into a line of
    dots ending in a number — the stylesheet's ``leader('.')`` by another
    name.
    """
    width = text_width(document.sections[0])
    for level, name in enumerate(TOC_STYLES, start=1):
        style = _new_style(document, name, WD_STYLE_TYPE.PARAGRAPH, builtin=True)
        _font(
            style,
            family(theme.fonts.body),
            size=theme.type.size,
            color=theme.colors.text,
            # Only the top level is set apart, as the stylesheet sets it.
            bold=level == 1 and theme.type.heading_weight >= BOLD_AT,
            italic=False,
        )
        paragraph = style.paragraph_format
        paragraph.left_indent = Pt(theme.type.size * TOC_INDENT * (level - 1))
        paragraph.space_before = Pt(
            theme.type.size * (TOC_SPACE_BEFORE if level == 1 else 0)
        )
        paragraph.space_after = Pt(theme.type.size * TOC_SPACE_AFTER)
        paragraph.line_spacing = HEADING_LEADING
        if width is not None:
            paragraph.tab_stops.add_tab_stop(
                width, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
            )


def text_width(section: Any) -> Length | None:
    """The width of the text column, which is the sheet less its margins.

    ``None`` when the section declares no width of its own: there is then
    nothing to measure a picture or a tab stop against, and whatever wanted
    one has to do without.
    """
    if section.page_width is None:
        return None
    return Emu(
        int(section.page_width)
        - int(section.left_margin or 0)
        - int(section.right_margin or 0)
    )


# --- page geometry --------------------------------------------------------


def quote_indent(theme: Theme) -> Length:
    """How far one level of quoting sets its content in.

    The ``Quote`` style carries this, and so does the walker — a paragraph
    with an indent of its own replaces the style's rather than adding to it,
    so the two have to agree on the step, and this is where they do.
    """
    return Pt(theme.type.size)


def apply_page(section: Any, theme: Theme, *, warn: Warn = _discard) -> None:
    """Set a section's sheet size and margins from the theme.

    A theme's page geometry is written as CSS, because the PDF path hands it
    straight to a paged-media descriptor. Word needs it as four numbers, and
    CSS is the larger language — so a value this cannot read is reported and
    stepped over rather than raised. A document that converts with the wrong
    margins and says so beats one that refuses to convert at all, given the
    same theme makes a PDF perfectly well.
    """
    size = page_size(theme.page.size)
    if size is None:
        warn(
            f"page size {theme.page.size!r} is not one the Word renderer "
            f"understands; keeping the default sheet."
        )
    else:
        section.page_width, section.page_height = size

    edges = page_margins(theme.page.margin)
    if edges is None:
        warn(
            f"margin {theme.page.margin!r} is not one the Word renderer "
            f"understands; keeping the default margins."
        )
    else:
        (
            section.top_margin,
            section.right_margin,
            section.bottom_margin,
            section.left_margin,
        ) = edges


def page_size(value: str) -> tuple[Length, Length] | None:
    """Read a CSS ``size`` descriptor as a width and a height.

    Understands what a theme is likely to say — ``A4``, ``Letter landscape``,
    ``210mm 297mm`` — and nothing more exotic.
    """
    words = value.lower().split()
    landscape = "landscape" in words
    words = [word for word in words if word not in {"portrait", "landscape"}]

    if len(words) == 1 and words[0] in NAMED_PAGE_SIZES:
        millimetres = NAMED_PAGE_SIZES[words[0]]
        sheet = (_from_units(millimetres[0], "mm"), _from_units(millimetres[1], "mm"))
    else:
        lengths = [length(word) for word in words]
        if not 1 <= len(lengths) <= 2 or None in lengths:
            return None
        measured = [item for item in lengths if item is not None]
        sheet = (measured[0], measured[-1])

    return (sheet[1], sheet[0]) if landscape else sheet


def page_margins(value: str) -> tuple[Length, Length, Length, Length] | None:
    """Read a CSS ``margin`` shorthand as top, right, bottom and left."""
    lengths = [length(word) for word in value.split()]
    if not 1 <= len(lengths) <= 4 or None in lengths:
        return None
    edges = [item for item in lengths if item is not None]
    if len(edges) == 1:
        edges *= 4
    elif len(edges) == 2:
        edges = [edges[0], edges[1], edges[0], edges[1]]
    elif len(edges) == 3:
        edges = [edges[0], edges[1], edges[2], edges[1]]
    return (edges[0], edges[1], edges[2], edges[3])


def length(value: str) -> Length | None:
    """One CSS length as Word's own unit, or ``None`` if it is not one."""
    match = LENGTH.match(value.strip().lower())
    if match is None:
        return None
    number, unit = match.groups()
    if not unit:
        # A bare number is a length only when it is zero; CSS says so, and a
        # theme that means centimetres has to write them.
        return Emu(0) if float(number) == 0 else None
    if unit not in UNITS_PER_INCH:
        return None
    return _from_units(float(number), unit)


def _from_units(value: float, unit: str) -> Length:
    return Emu(round(value * EMU_PER_INCH / UNITS_PER_INCH[unit]))


# --- fonts and colour -----------------------------------------------------


def family(stack: Sequence[str]) -> str:
    """Reduce a CSS font stack to the one name a Word style can hold.

    A stack's later entries are fallbacks, and Word does its own falling back
    from a single name, so the first real family is the one to keep. Generic
    families are skipped rather than passed through: Word would read
    ``ui-monospace`` as the name of a font nobody has and quietly set code in
    the body face.
    """
    for name in stack:
        if name.lower() not in GENERIC_FAMILIES:
            return name
    return GENERIC_FAMILIES[stack[0].lower()]


def rgb(value: str) -> RGBColor:
    """A theme colour as Word wants it: three bytes."""
    return RGBColor.from_string(value.lstrip("#").upper())


def _new_style(
    document: Any, name: str, kind: WD_STYLE_TYPE, *, builtin: bool = False
) -> Any:
    """Add a style, or return the one already there under that name.

    A paragraph style Amethyst defines is based on ``Normal``, which the theme
    has already been applied to, so it starts from the document's own type
    rather than from Word's factory defaults and only has to say what differs.
    """
    try:
        return document.styles[name]
    except KeyError:
        style = document.styles.add_style(name, kind, builtin=builtin)
    if kind == WD_STYLE_TYPE.PARAGRAPH:
        style.base_style = document.styles[BODY_STYLE]
    return style


def _font(
    style: Any,
    name: str | None = None,
    *,
    size: float | None = None,
    color: str | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> None:
    """Set what a style says about its type, and unbind it from Word's theme.

    The unbinding is the part that is easy to miss. A built-in heading style
    names its font twice — once plainly and once as a reference to the document
    theme's major font — and the reference wins, so a style whose ``w:ascii``
    was set and whose ``w:asciiTheme`` was left alone still comes out in
    Calibri.
    """
    if name is not None:
        style.font.name = name
        _unbind_theme_font(style)
    if size is not None:
        # Word stores a size in half-points and truncates what it is given, so
        # a scale step that lands between two of them — 11pt × 1.22 — would
        # come out a third of a point smaller than asked for. Rounding first
        # costs nothing and keeps the two formats on the same scale.
        style.font.size = Pt(round(size * 2) / 2)
    if color is not None:
        style.font.color.rgb = rgb(color)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic


def _unbind_theme_font(style: Any) -> None:
    """Remove the theme references that outrank a plainly named font."""
    fonts = style.element.get_or_add_rPr().find(qn("w:rFonts"))
    if fonts is None:
        return
    for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fonts.attrib.pop(qn(f"w:{attribute}"), None)


__all__ = [
    "BODY_STYLE",
    "BULLET_STYLES",
    "CODE_INLINE_STYLE",
    "CODE_STYLE",
    "COVER_DATE_STYLE",
    "COVER_SPACE_AFTER",
    "FOOTNOTE_STYLE",
    "FOOTER_STYLE",
    "HEADER_STYLE",
    "HEADING_STYLES",
    "LINK_STYLE",
    "LIST_INDENT_STEP",
    "NUMBER_STYLES",
    "QUOTE_STYLE",
    "SUBTITLE_STYLE",
    "TABLE_STYLE",
    "TABLE_TEXT_STYLE",
    "TITLE_PAGE_OFFSET",
    "TITLE_STYLE",
    "TOC_HEADING_STYLE",
    "TOC_STYLES",
    "apply_page",
    "apply_theme",
    "family",
    "length",
    "page_margins",
    "page_size",
    "quote_indent",
    "rgb",
    "text_width",
]
