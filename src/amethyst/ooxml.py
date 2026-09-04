"""The OOXML that python-docx has no API for.

python-docx covers paragraphs, runs, styles, tables and pictures, which is
most of the job. What it does not cover is the furniture: hyperlinks,
bookmarks, shading, borders, field codes, a repeating table header, and a
numbering instance that starts again at one. Each of those is a handful of
elements built by hand, and they live here — together, and away from the
walker — because they are fiddly, individually testable, and will be returned
to.

This module sits under neither pipeline, which is the point. Both the Word
renderer and the theme compiler need these elements, and a module inside
``render/`` that ``theme/`` imported would close a circle: importing it runs
``render/__init__``, which imports the walker, which imports the theme
compiler again.

The one thing that matters everywhere below: Word validates a document against
the schema when it opens it, and rejects the whole file when a child element
is in the wrong place. So the *order* of the children of a properties element
is as load-bearing as their content. Every sequence the format demands is
written out once in ``CHILD_ORDER``, and every helper inserts through it
rather than appending and hoping.

Nothing here imports anything else from Amethyst. These are facts about the
file format, not about this program.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

#: The order the schema demands of the children of each properties element,
#: for the ones this project writes into. Only the elements before the one
#: being inserted matter, but the sequences are written out in full: a partial
#: list is a trap for whoever adds the next helper.
CHILD_ORDER: dict[str, tuple[str, ...]] = {
    "pPr": (
        "w:pStyle",
        "w:keepNext",
        "w:keepLines",
        "w:pageBreakBefore",
        "w:framePr",
        "w:widowControl",
        "w:numPr",
        "w:suppressLineNumbers",
        "w:pBdr",
        "w:shd",
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    ),
    "rPr": (
        "w:rStyle",
        "w:rFonts",
        "w:b",
        "w:bCs",
        "w:i",
        "w:iCs",
        "w:caps",
        "w:smallCaps",
        "w:strike",
        "w:dstrike",
        "w:outline",
        "w:shadow",
        "w:emboss",
        "w:imprint",
        "w:noProof",
        "w:snapToGrid",
        "w:vanish",
        "w:webHidden",
        "w:color",
        "w:spacing",
        "w:w",
        "w:kern",
        "w:position",
        "w:sz",
        "w:szCs",
        "w:highlight",
        "w:u",
        "w:effect",
        "w:bdr",
        "w:shd",
        "w:fitText",
        "w:vertAlign",
        "w:rtl",
        "w:cs",
        "w:em",
        "w:lang",
        "w:eastAsianLayout",
        "w:specVanish",
        "w:oMath",
    ),
    "tblPr": (
        "w:tblStyle",
        "w:tblpPr",
        "w:tblOverlap",
        "w:bidiVisual",
        "w:tblStyleRowBandSize",
        "w:tblStyleColBandSize",
        "w:tblW",
        "w:jc",
        "w:tblCellSpacing",
        "w:tblInd",
        "w:tblBorders",
        "w:shd",
        "w:tblLayout",
        "w:tblCellMar",
        "w:tblLook",
        "w:tblCaption",
        "w:tblDescription",
    ),
    "tcPr": (
        "w:cnfStyle",
        "w:tcW",
        "w:gridSpan",
        "w:hMerge",
        "w:vMerge",
        "w:tcBorders",
        "w:shd",
        "w:noWrap",
        "w:tcMar",
        "w:textDirection",
        "w:tcFitText",
        "w:vAlign",
        "w:hideMark",
    ),
    "trPr": (
        "w:cnfStyle",
        "w:divId",
        "w:gridBefore",
        "w:gridAfter",
        "w:wBefore",
        "w:wAfter",
        "w:cantSplit",
        "w:trHeight",
        "w:tblHeader",
        "w:tblCellSpacing",
        "w:jc",
        "w:hidden",
    ),
    "pBdr": ("w:top", "w:left", "w:bottom", "w:right", "w:between", "w:bar"),
    "tblBorders": (
        "w:top",
        "w:left",
        "w:bottom",
        "w:right",
        "w:insideH",
        "w:insideV",
    ),
    "tcBorders": (
        "w:top",
        "w:left",
        "w:bottom",
        "w:right",
        "w:insideH",
        "w:insideV",
        "w:tl2br",
        "w:tr2bl",
    ),
}

#: Which element holds the borders, for each properties element that can have
#: them. The three are the same shape and spelled three different ways, which
#: is the sort of thing worth stating once.
BORDER_CONTAINER = {
    "pPr": "w:pBdr",
    "tblPr": "w:tblBorders",
    "tcPr": "w:tcBorders",
}

#: Border width, in the eighths of a point the format measures it in. Six is
#: the 0.75pt that a CSS ``1px`` rule comes to on paper.
HAIRLINE = 6

#: What Word allows in a bookmark name: letters, digits and underscores, up to
#: forty characters, not starting with a digit. Heading anchors are slugs with
#: hyphens in them, so every one of them has to be translated.
BOOKMARK_UNSAFE = re.compile(r"[^0-9A-Za-z_]+")
BOOKMARK_MAX_LENGTH = 40


# --- properties -----------------------------------------------------------


def properties_child(properties: Any, tag: str) -> Any:
    """Return a child of a properties element, adding it in schema order."""
    existing = properties.find(qn(tag))
    if existing is not None:
        return existing
    element = OxmlElement(tag)
    _insert(properties, element, tag)
    return element


def _insert(parent: Any, element: Any, tag: str) -> None:
    """Put ``element`` in front of the first sibling that must follow it.

    Insertion is done here rather than through python-docx's own
    ``insert_element_before`` because that method belongs to the element
    classes python-docx registers, and half the elements built in this module
    — ``w:pBdr``, ``w:tblBorders`` — are not among them and come back as plain
    lxml.
    """
    sequence = CHILD_ORDER[_local_name(parent)]
    following = {qn(name) for name in sequence[sequence.index(tag) + 1 :]}
    for child in parent:
        if child.tag in following:
            child.addprevious(element)
            return
    parent.append(element)


def shade(properties: Any, fill: str) -> None:
    """Fill the background of whatever ``properties`` describes.

    Serves a paragraph, a run, a table and a table cell alike: ``w:shd`` is
    spelled the same in all four, and only its position among its siblings
    changes.
    """
    element = properties_child(properties, "w:shd")
    element.set(qn("w:val"), "clear")
    element.set(qn("w:color"), "auto")
    element.set(qn("w:fill"), _hex(fill))


def set_borders(
    properties: Any,
    edges: Iterable[str],
    *,
    color: str,
    size: int = HAIRLINE,
    space: int = 0,
    style: str = "single",
) -> None:
    """Draw ``edges`` — "top", "left", "bottom", "right", "insideH", … .

    ``size`` is in eighths of a point and ``space`` in points, because that is
    what the format measures them in and translating here would only hide it.
    """
    container = properties_child(properties, BORDER_CONTAINER[_local_name(properties)])
    for edge in edges:
        tag = f"w:{edge}"
        element = OxmlElement(tag)
        element.set(qn("w:val"), style)
        element.set(qn("w:sz"), str(size))
        element.set(qn("w:space"), str(space))
        element.set(qn("w:color"), _hex(color))
        _insert(container, element, tag)


def clear_properties_child(properties: Any, tag: str) -> None:
    """Take a child off a properties element, if it is there at all.

    The counterpart of :func:`properties_child`, and needed because Word's
    built-in styles arrive carrying things a theme has to undo rather than
    override — a rule drawn under ``Title`` in an accent colour that belongs
    to no theme here, or the stray numbering reference on ``Subtitle``.
    """
    element = properties.find(qn(tag))
    if element is not None:
        properties.remove(element)


def repeat_as_header(row: Any) -> None:
    """Mark a table row as the header, so it repeats on every page.

    The counterpart of ``thead { display: table-header-group }`` in the PDF
    stylesheet: a table split across a page break is only readable because its
    column headings come back at the top of the next one.
    """
    properties_child(row._tr.get_or_add_trPr(), "w:tblHeader")


# --- links and bookmarks --------------------------------------------------


def bookmark_name(anchor: str) -> str:
    """Translate a heading's HTML id into a name Word will accept.

    Word's rules are much tighter than HTML's — no hyphens, no leading digit,
    forty characters — so this is lossy by necessity. It is deterministic,
    which is the property that matters: the heading and the link that points
    at it are translated by the same function and so agree.
    """
    cleaned = BOOKMARK_UNSAFE.sub("_", anchor).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned[:BOOKMARK_MAX_LENGTH]


def bookmark(paragraph: Any, name: str, identifier: int) -> None:
    """Mark a paragraph as the destination of an internal link."""
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(identifier))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(identifier))

    paragraph_element = paragraph._p
    properties = paragraph_element.find(qn("w:pPr"))
    if properties is None:
        paragraph_element.insert(0, start)
    else:
        properties.addnext(start)
    paragraph_element.append(end)


def link(
    paragraph: Any,
    elements: Sequence[Any],
    *,
    url: str | None = None,
    anchor: str | None = None,
) -> None:
    """Wrap already-written runs in a hyperlink, external or internal.

    The runs are built first and moved in afterwards rather than the other way
    round, so the code that renders a link's text is the same code that
    renders every other run — a link's label is Markdown like any other, and
    can hold bold, code and an image.
    """
    if not elements:
        return
    element = OxmlElement("w:hyperlink")
    if url is not None:
        relationship = paragraph.part.relate_to(
            url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True
        )
        element.set(qn("r:id"), relationship)
    if anchor is not None:
        element.set(qn("w:anchor"), anchor)
    elements[0].addprevious(element)
    for run in elements:
        element.append(run)


# --- fields ---------------------------------------------------------------


def field(
    paragraph: Any, instruction: str, placeholder: str = "", *, dirty: bool = False
) -> None:
    """Append a field — ``PAGE``, ``PAGEREF``, ``STYLEREF`` — to a paragraph.

    A field is not a value but an instruction that Word evaluates when it
    opens the document, which is the only way to write something that has to
    know a page number the writer cannot know. The placeholder is what a
    reader that does not evaluate fields shows instead.

    ``dirty`` asks Word to evaluate the field as soon as it opens the file
    rather than showing the placeholder until someone presses F9. It is what a
    field with no useful placeholder — a page number nothing here can compute
    — needs to arrive filled in.
    """
    for child in (
        *field_start(instruction, dirty=dirty),
        _text_run(placeholder),
        field_end(),
    ):
        paragraph._p.append(child)


def field_start(instruction: str, *, dirty: bool = False) -> tuple[Any, ...]:
    """The runs that open a field, up to where its result begins.

    Separate from :func:`field` because a field's result is not always one
    run in one paragraph: a table of contents is a run of paragraphs, and the
    only way to write one is to open the field in the first and close it in
    the last.
    """
    return (
        _field_char("begin", dirty=dirty),
        _instruction(instruction),
        _field_char("separate"),
    )


def field_end() -> Any:
    """The run that closes a field opened by :func:`field_start`."""
    return _field_char("end")


def _field_char(kind: str, *, dirty: bool = False) -> Any:
    run = OxmlElement("w:r")
    char = OxmlElement("w:fldChar")
    char.set(qn("w:fldCharType"), kind)
    if dirty:
        char.set(qn("w:dirty"), "true")
    run.append(char)
    return run


def _instruction(instruction: str) -> Any:
    run = OxmlElement("w:r")
    text = OxmlElement("w:instrText")
    # Without this the leading and trailing spaces a field instruction needs
    # are collapsed away, and Word reads a different instruction than the one
    # that was written.
    text.set(qn("xml:space"), "preserve")
    text.text = f" {instruction} "
    run.append(text)
    return run


def _text_run(content: str) -> Any:
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = content
    run.append(text)
    return run


# --- numbering ------------------------------------------------------------


def numbering_instance(document: Any, style_name: str, *, start: int = 1) -> int:
    """Give one list its own counter, and return the id to point at it with.

    Word's numbering styles carry a counter each, not a counter per list, so
    every ordered list in a document that uses ``List Number`` shares one — and
    the second list in a document carries on from where the first stopped
    instead of starting again at one. The cure is an instance of its own per
    list, pointing at the same shape and overriding where it starts.
    """
    numbering = document.part.numbering_part.element
    abstract_id = _abstract_num_id(document, style_name)

    identifier = 1 + max(
        (
            int(existing.get(qn("w:numId")) or 0)
            for existing in numbering.findall(qn("w:num"))
        ),
        default=0,
    )
    instance = OxmlElement("w:num")
    instance.set(qn("w:numId"), str(identifier))
    reference = OxmlElement("w:abstractNumId")
    reference.set(qn("w:val"), str(abstract_id))
    instance.append(reference)

    override = OxmlElement("w:lvlOverride")
    override.set(qn("w:ilvl"), "0")
    first = OxmlElement("w:startOverride")
    first.set(qn("w:val"), str(start))
    override.append(first)
    instance.append(override)

    # Every w:num follows every w:abstractNum, so the end of the part is the
    # one position that is always right.
    numbering.append(instance)
    return identifier


def set_numbering(paragraph: Any, identifier: int, level: int = 0) -> None:
    """Point a paragraph at a numbering instance, overriding its style's."""
    properties = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    properties.get_or_add_ilvl().val = level
    properties.get_or_add_numId().val = identifier


def _abstract_num_id(document: Any, style_name: str) -> int:
    """The numbering shape a built-in list style draws its bullets from."""
    style = document.styles[style_name]
    reference = style.element.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}")
    if reference is None:
        raise KeyError(f"style {style_name!r} carries no numbering")
    wanted = reference.get(qn("w:val"))
    numbering = document.part.numbering_part.element
    for instance in numbering.findall(qn("w:num")):
        if instance.get(qn("w:numId")) == wanted:
            abstract = instance.find(qn("w:abstractNumId"))
            if abstract is not None:
                return int(abstract.get(qn("w:val")))
    raise KeyError(
        f"style {style_name!r} points at numbering {wanted!r}, which is not there"
    )


# --- shared ---------------------------------------------------------------


def _local_name(element: Any) -> str:
    """The tag without its namespace: ``{...}pPr`` is ``pPr``."""
    return str(element.tag).rpartition("}")[2]


def _hex(color: str) -> str:
    """A theme colour as OOXML writes it: six digits, no leading hash."""
    return color.lstrip("#").upper()


__all__ = [
    "BOOKMARK_MAX_LENGTH",
    "CHILD_ORDER",
    "HAIRLINE",
    "bookmark",
    "bookmark_name",
    "clear_properties_child",
    "field",
    "field_end",
    "field_start",
    "link",
    "numbering_instance",
    "properties_child",
    "repeat_as_header",
    "set_borders",
    "set_numbering",
    "shade",
]
