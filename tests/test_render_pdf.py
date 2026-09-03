"""The PDF pipeline: the standalone HTML in the middle, the PDF at the end.

The HTML half is tested on its own because it is cheap and exact — a string
either contains the rule or it does not. The PDF half is tested through what
``pypdf`` can read back: page count, extracted text, outline, embedded images.
No pixel comparison; it is brittle, platform-dependent, and would fail on a
machine with different fonts installed for reasons that are not bugs.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from pypdf import PdfReader

from amethyst.document import Document, load_document
from amethyst.errors import MissingDependencyError, RenderError
from amethyst.render import RenderOptions, render_html, render_pdf
from amethyst.render.pdf import (
    DYLD_FALLBACK_PATH,
    _add_homebrew_libraries_to_search_path,
    _dependency_error,
    local_only_fetcher,
)
from amethyst.theme import default_theme
from amethyst.theme.to_css import page_css

#: A4 and Letter in PDF points, to a whole number.
A4_POINTS = (595, 842)
LETTER_POINTS = (612, 792)


def parse(text: str, base_dir: Path | None = None) -> Document:
    return Document.from_markdown(text, base_dir=base_dir or Path.cwd())


def paged(**geometry: str) -> RenderOptions:
    """Options whose theme carries the page geometry a flag would override."""
    return RenderOptions(theme=default_theme().with_page(**geometry))


def read_pdf(data: bytes) -> PdfReader:
    """Open rendered bytes without going via the filesystem."""
    return PdfReader(io.BytesIO(data))


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in read_pdf(data).pages)


# --- the HTML half --------------------------------------------------------


def test_the_html_is_a_standalone_document():
    html = render_html(parse("# Hello\n\nBody.\n"), RenderOptions())
    assert html.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in html
    assert '<h1 id="hello">Hello</h1>' in html
    # The stylesheet is inlined, not linked: nothing must be fetched to render.
    assert "<link" not in html
    assert "--font-body:" in html


def test_the_title_comes_from_the_document_and_is_escaped():
    document = parse("---\ntitle: Angle <brackets> & ampersands\n---\n\nBody.\n")
    html = render_html(document, RenderOptions())
    assert "<title>Angle &lt;brackets&gt; &amp; ampersands</title>" in html


def test_a_document_with_no_title_still_gets_one():
    assert "<title>Untitled</title>" in render_html(parse("Body.\n"), RenderOptions())


def test_the_page_block_follows_the_theme():
    css = page_css(default_theme().with_page(size="Letter", margin="3cm 2cm"))
    assert "size: Letter;" in css
    assert "margin: 3cm 2cm;" in css
    assert "counter(page)" in css


def test_page_numbers_can_be_left_out():
    assert "counter(page)" not in page_css(default_theme(), page_numbers=False)


def test_an_ordered_list_starts_where_the_author_said():
    """WeasyPrint 69 does not read <ol start>, so the counter is set in CSS.

    Checked against WeasyPrint with none of Amethyst's stylesheet loaded, so
    the gap is the renderer's rather than something base.css does. Without
    this the Word file numbers the list from four and the PDF from one.
    """
    html = render_html(parse("Text:\n\n4. four\n5. five\n"), RenderOptions())
    assert '<ol start="4" style="counter-reset: list-item 3">' in html


def test_a_list_that_starts_at_one_gets_no_counter_of_its_own():
    html = render_html(parse("1. one\n2. two\n"), RenderOptions())
    assert "<ol>" in html


def test_rendering_leaves_the_document_tokens_as_it_found_them():
    """The Word renderer walks the same tokens, and wants no CSS on them."""
    document = parse("4. four\n")
    render_html(document, RenderOptions())
    render_html(document, RenderOptions())
    listing = next(
        token for token in document.tokens if token.type == "ordered_list_open"
    )
    assert listing.attrs == {"start": 4}


def test_the_page_numbering_of_a_started_list_reaches_the_pdf(requires_weasyprint):
    text = pdf_text(render_pdf(parse("Text:\n\n4. four\n5. five\n"), paged()).data)
    assert "4." in text
    assert "5." in text


def test_extra_css_is_appended_after_everything_else(tmp_path):
    extra = tmp_path / "extra.css"
    extra.write_text("p { color: rebeccapurple }\n", encoding="utf-8")
    html = render_html(parse("Body.\n"), RenderOptions(extra_css=extra))
    assert html.index("rebeccapurple") > html.index("@page")


def test_unreadable_extra_css_is_reported_not_raised_raw(tmp_path):
    with pytest.raises(RenderError, match="Could not read the CSS"):
        render_html(parse("Body.\n"), RenderOptions(extra_css=tmp_path / "gone.css"))


# --- the PDF half ---------------------------------------------------------


def test_the_kitchen_sink_becomes_a_readable_pdf(kitchen_sink, requires_weasyprint):
    result = render_pdf(load_document(kitchen_sink), RenderOptions())

    assert result.data.startswith(b"%PDF-")
    assert result.pages is not None and result.pages > 1
    assert result.pages == len(read_pdf(result.data).pages)

    text = pdf_text(result.data)
    for expected in [
        "Kitchen sink",  # heading
        "struck through",  # inline formatting
        "Ordered second",  # nested ordered list
        "def convert",  # fenced code
        "attribution line",  # blockquote
        "Right column",  # table cell
        "A TOML file declaring",  # definition list
        "Rendered by WeasyPrint",  # footnote body
        "A raw HTML block",  # passed-through HTML
    ]:
        assert expected in text, expected


def test_headings_become_a_nested_outline(kitchen_sink, requires_weasyprint):
    result = render_pdf(load_document(kitchen_sink), RenderOptions())
    outline = read_pdf(result.data).outline

    # One top-level entry, the h1, with the h2s nested inside it.
    assert [item.title for item in outline if not isinstance(item, list)] == [
        "Kitchen sink"
    ]
    nested = [
        item.title
        for group in outline
        if isinstance(group, list)
        for item in group
        if not isinstance(item, list)
    ]
    assert "Inline formatting" in nested
    assert "Footnotes" in nested


def test_the_page_size_is_honoured(requires_weasyprint):
    def size(page_size: str) -> tuple[int, int]:
        result = render_pdf(parse("Body.\n"), paged(size=page_size))
        box = read_pdf(result.data).pages[0].mediabox
        return round(float(box.width)), round(float(box.height))

    assert size("A4") == A4_POINTS
    assert size("Letter") == LETTER_POINTS


def test_the_margin_is_honoured(requires_weasyprint):
    """Measured by its consequence: a wider margin is a shorter column."""
    body = "word " * 900
    narrow = render_pdf(parse(body), paged(margin="1cm"))
    wide = render_pdf(parse(body), paged(margin="5cm"))
    assert wide.pages > narrow.pages


def test_page_numbers_can_be_suppressed(requires_weasyprint):
    body = "Only words here, no numerals.\n"
    numbered = pdf_text(render_pdf(parse(body), RenderOptions()).data)
    plain = pdf_text(render_pdf(parse(body), RenderOptions(page_numbers=False)).data)
    assert "1" in numbered
    assert "1" not in plain


def test_a_local_image_is_embedded(kitchen_sink, requires_weasyprint):
    result = render_pdf(load_document(kitchen_sink), RenderOptions())
    embedded = read_pdf(result.data).pages[0].images
    assert [image.name for image in embedded] != []


def test_a_remote_image_is_reported_rather_than_fetched(
    kitchen_sink, requires_weasyprint
):
    warnings: list[str] = []
    render_pdf(load_document(kitchen_sink), RenderOptions(warn=warnings.append))
    assert any("not-a-real-image.png" in message for message in warnings)


def test_the_url_fetcher_refuses_the_network_without_touching_it(requires_weasyprint):
    """The refusal is what keeps a conversion — and this suite — offline."""
    import weasyprint  # noqa: PLC0415

    fetcher = local_only_fetcher(weasyprint)
    for url in ("https://example.com/image.png", "http://example.com/image.png"):
        with pytest.raises(ValueError, match="remote resources"):
            fetcher.fetch(url)
    with pytest.raises(ValueError, match="disallowed protocol"):
        fetcher.fetch("ftp://example.com/image.png")


# --- the dependency error -------------------------------------------------


def test_absent_pango_is_told_to_install_it(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("amethyst.render.pdf._installed_pango_dir", lambda: None)
    error = _dependency_error(OSError("cannot load library 'libgobject-2.0-0'"))
    assert isinstance(error, MissingDependencyError)
    assert error.exit_code == 3
    assert "brew install pango" in (error.hint or "")


def test_installed_but_unloadable_pango_is_not_told_to_install_it(monkeypatch):
    """The circular-advice case: telling someone to install what they installed."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "amethyst.render.pdf._installed_pango_dir", lambda: Path("/opt/homebrew/lib")
    )
    error = _dependency_error(OSError("cannot load library 'libgobject-2.0-0'"))
    assert "/opt/homebrew/lib" in error.message
    assert "brew install" not in (error.hint or "")


# --- the macOS library search path ----------------------------------------


def test_homebrews_libraries_are_put_on_the_search_path(monkeypatch, tmp_path):
    """The repair that lets the installed console script work at all.

    Exporting the variable in a shell cannot reach it: the console script is a
    /bin/sh wrapper, and macOS strips DYLD_* when it runs one.
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("amethyst.render.pdf._installed_pango_dir", lambda: tmp_path)
    monkeypatch.delenv(DYLD_FALLBACK_PATH, raising=False)

    _add_homebrew_libraries_to_search_path()
    assert os.environ[DYLD_FALLBACK_PATH] == str(tmp_path)

    # Running twice must not stack up duplicate entries.
    _add_homebrew_libraries_to_search_path()
    assert os.environ[DYLD_FALLBACK_PATH] == str(tmp_path)


def test_an_existing_search_path_is_added_to_not_replaced(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("amethyst.render.pdf._installed_pango_dir", lambda: tmp_path)
    monkeypatch.setenv(DYLD_FALLBACK_PATH, "/somewhere/else")

    _add_homebrew_libraries_to_search_path()
    assert os.environ[DYLD_FALLBACK_PATH].split(os.pathsep) == [
        "/somewhere/else",
        str(tmp_path),
    ]


def test_nothing_is_touched_off_macos(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("amethyst.render.pdf._installed_pango_dir", lambda: tmp_path)
    monkeypatch.delenv(DYLD_FALLBACK_PATH, raising=False)

    _add_homebrew_libraries_to_search_path()
    assert DYLD_FALLBACK_PATH not in os.environ


def test_a_missing_weasyprint_is_not_blamed_on_pango():
    error = _dependency_error(ModuleNotFoundError(name="weasyprint"))
    assert "WeasyPrint is not installed" in error.message
    assert "pango" not in (error.hint or "").lower()
