"""The parse layer: frontmatter, plugin wiring, asset resolution, Document."""

from __future__ import annotations

from pathlib import Path

import pytest

from amethyst.document import Document, load_document
from amethyst.errors import InputError
from amethyst.parse import AssetKind, build_parser, parse_frontmatter, resolve_assets


def parse(text: str, **kwargs) -> Document:
    return Document.from_markdown(text, **kwargs)


def block_types(document: Document) -> list[str]:
    return [token.type for token in document.tokens]


def inline_children(document: Document) -> list:
    return [
        child
        for token in document.tokens
        if token.type == "inline" and token.children
        for child in token.children
    ]


# --- frontmatter ---------------------------------------------------------


def test_absent_frontmatter_gives_empty_metadata():
    document = parse("# Just a heading\n")
    assert document.metadata == {}
    assert block_types(document)[0] == "heading_open"


def test_empty_frontmatter_gives_empty_metadata():
    document = parse("---\n---\n\n# Heading\n")
    assert document.metadata == {}
    assert "front_matter" not in block_types(document)


def test_frontmatter_keys_are_lowercased_and_stripped():
    document = parse('---\nTitle: Cased\n"  Author  ": Someone\n---\n')
    assert document.metadata["title"] == "Cased"
    assert document.metadata["author"] == "Someone"


def test_frontmatter_token_is_removed_but_line_maps_are_not_shifted():
    text = "---\ntitle: T\n---\n\n# Heading on line 5\n"
    document = parse(text)
    assert "front_matter" not in block_types(document)
    heading = next(t for t in document.tokens if t.type == "heading_open")
    assert heading.map is not None
    assert text.splitlines()[heading.map[0]] == "# Heading on line 5"


def test_malformed_frontmatter_is_an_input_error_naming_the_file_line():
    with pytest.raises(InputError) as excinfo:
        parse("---\ntitle: [unclosed\n---\n\nBody\n")
    assert excinfo.value.hint is not None
    # The mark counts from inside the block; the hint must point at the file,
    # where the unclosed bracket is on line 2.
    assert "line 2 of the file" in excinfo.value.hint


def test_non_mapping_frontmatter_is_an_input_error():
    with pytest.raises(InputError) as excinfo:
        parse("---\n- one\n- two\n---\n\nBody\n")
    assert "not a set of key: value pairs" in excinfo.value.message


def test_frontmatter_values_keep_their_yaml_types():
    metadata = parse_frontmatter("date: 2026-08-31\ndraft: true\ntags: [a, b]")
    assert metadata["date"].isoformat() == "2026-08-31"
    assert metadata["draft"] is True
    assert metadata["tags"] == ["a", "b"]


# --- metadata as display text --------------------------------------------


def test_author_list_is_joined_and_date_is_rendered_as_text():
    document = parse("---\nauthor:\n  - Ada\n  - Grace\ndate: 2026-08-31\n---\n")
    assert document.author == "Ada, Grace"
    assert document.date == "2026-08-31"


def test_title_falls_back_to_the_first_h1_with_markup_stripped():
    document = parse("# A *typeset* `document`\n\n# Second\n")
    assert document.title == "A typeset document"


def test_frontmatter_title_beats_the_first_heading():
    document = parse("---\ntitle: Declared\n---\n\n# Heading\n")
    assert document.title == "Declared"


def test_title_is_none_when_there_is_neither():
    assert parse("## Only an h2\n\nBody.\n").title is None


def test_blank_metadata_values_read_as_absent():
    document = parse("---\ntitle: '   '\nauthor:\n---\n\n# Heading\n")
    assert document.title == "Heading"
    assert document.author is None


# --- parser configuration -------------------------------------------------


def test_gfm_tables_strikethrough_and_linkify_are_enabled():
    document = parse(
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n~~gone~~ https://example.com\n"
    )
    assert "table_open" in block_types(document)
    types = {child.type for child in inline_children(document)}
    assert {"s_open", "link_open"} <= types


def test_rendering_exercises_linkify_which_fails_late_when_uninstalled():
    # linkify-it-py raises at render time, not import time — so only a render
    # proves the dependency is actually present.
    html = build_parser().render("See https://example.com for more.\n")
    assert 'href="https://example.com"' in html


def test_plugins_supply_footnotes_deflists_tasklists_and_anchors():
    document = parse(
        "# Heading\n\n"
        "###### Deep\n\n"
        "Text[^a]\n\n"
        "[^a]: The note.\n\n"
        "Term\n: Definition\n\n"
        "- [x] done\n"
    )
    types = block_types(document)
    assert "footnote_block_open" in types
    assert "dl_open" in types

    checkboxes = [
        child
        for child in inline_children(document)
        if child.type == "html_inline" and "task-list-item-checkbox" in child.content
    ]
    assert len(checkboxes) == 1
    assert "checked" in checkboxes[0].content

    ids = [t.attrGet("id") for t in document.tokens if t.type == "heading_open"]
    assert ids == ["heading", "deep"]  # anchors reach every level, not just h1-h3


# --- asset resolution -----------------------------------------------------


def test_local_image_is_resolved_and_rewritten_to_an_absolute_path(write_md):
    source = write_md("doc.md", "![pic](img/a.png)\n")
    image = source.parent / "img" / "a.png"
    image.parent.mkdir()
    image.write_bytes(b"not really a png")

    document = load_document(source)
    asset = document.assets[0]
    assert asset.kind is AssetKind.image
    assert asset.path == image.resolve()
    assert not asset.is_missing
    assert document.missing_assets == []

    src = next(c for c in inline_children(document) if c.type == "image").attrGet("src")
    assert src == str(image.resolve())


def test_images_resolve_against_the_source_file_not_the_working_directory(
    write_md, tmp_path, monkeypatch
):
    source = write_md("nested/doc.md", "![up](../sibling/a.png)\n")
    image = tmp_path / "sibling" / "a.png"
    image.parent.mkdir()
    image.write_bytes(b"x")
    monkeypatch.chdir(tmp_path / "nested")

    document = load_document(source)
    assert document.assets[0].path == image.resolve()
    assert not document.assets[0].is_missing


def test_missing_image_is_reported_and_left_as_written(write_md):
    document = load_document(write_md("doc.md", "\n\n![pic](nope.png)\n"))
    asset = document.assets[0]
    assert asset.is_missing
    assert asset.reference == "nope.png"
    assert asset.line == 3  # 1-based, so it can be quoted in a warning
    assert document.missing_assets == [asset]

    src = next(c for c in inline_children(document) if c.type == "image").attrGet("src")
    assert src == "nope.png"


def test_percent_encoded_names_and_fragments_resolve_to_real_paths(write_md):
    source = write_md("doc.md", "![a](my%20image.png)\n\n![b](img.png#frag)\n")
    (source.parent / "my image.png").write_bytes(b"x")
    (source.parent / "img.png").write_bytes(b"x")

    document = load_document(source)
    assert [asset.path.name for asset in document.assets] == ["my image.png", "img.png"]
    assert document.missing_assets == []


def test_remote_images_are_recorded_but_never_rewritten(write_md):
    url = "https://example.com/a.png"
    document = load_document(write_md("doc.md", f"![r]({url})\n"))
    asset = document.assets[0]
    assert asset.is_remote
    assert asset.path is None
    assert not asset.is_missing

    src = next(c for c in inline_children(document) if c.type == "image").attrGet("src")
    assert src == url


def test_references_with_nothing_to_resolve_are_skipped(write_md):
    document = load_document(
        write_md(
            "doc.md",
            "![d](data:image/png;base64,AAAA)\n\n"
            "[m](mailto:someone@example.com)\n\n"
            "[a](#section)\n\n"
            "[e](https://example.com)\n",
        )
    )
    assert document.assets == []


def test_local_links_are_recorded_but_not_rewritten(write_md):
    source = write_md("doc.md", "[notes](other.md)\n")
    (source.parent / "other.md").write_text("x")

    document = load_document(source)
    asset = document.assets[0]
    assert asset.kind is AssetKind.link
    assert asset.path == (source.parent / "other.md").resolve()

    href = next(c for c in inline_children(document) if c.type == "link_open").attrGet(
        "href"
    )
    assert href == "other.md"


def test_resolve_assets_tolerates_a_stream_with_no_references():
    tokens = build_parser().parse("Just words.\n")
    assert resolve_assets(tokens, Path.cwd()) == []


# --- reading --------------------------------------------------------------


def test_stdin_documents_resolve_against_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin("# From a pipe\n"))
    document = load_document(None)
    assert document.source is None
    assert document.base_dir == tmp_path
    assert document.title == "From a pipe"


def test_a_byte_order_mark_does_not_end_up_in_the_title(write_md):
    source = write_md("doc.md", "# Heading\n")
    source.write_bytes(b"\xef\xbb\xbf" + source.read_bytes())
    assert load_document(source).title == "Heading"


def test_a_missing_file_is_an_input_error_not_a_traceback(tmp_path):
    with pytest.raises(InputError, match="No such file"):
        load_document(tmp_path / "absent.md")


def test_a_non_utf8_file_is_an_input_error(write_md):
    source = write_md("doc.md", "placeholder\n")
    source.write_bytes(b"# Heading \xff\xfe not utf-8\n")
    with pytest.raises(InputError, match="not valid UTF-8"):
        load_document(source)


# --- the kitchen sink -----------------------------------------------------


def test_kitchen_sink_parses_with_every_reference_resolved(kitchen_sink):
    document = load_document(kitchen_sink)
    assert document.title == "The Amethyst Kitchen Sink"
    assert document.author == "Patrik Repkovsky"
    assert document.date == "2026-08-31"
    assert document.base_dir == kitchen_sink.parent.resolve()
    assert document.missing_assets == []

    local = [a for a in document.assets if a.path is not None]
    remote = [a for a in document.assets if a.is_remote]
    assert [a.path.name for a in local] == ["amethyst.png"]
    assert len(remote) == 1


def test_kitchen_sink_covers_every_feature_the_matrix_promises(kitchen_sink):
    document = load_document(kitchen_sink)
    types = set(block_types(document))
    assert {
        "heading_open",
        "paragraph_open",
        "bullet_list_open",
        "ordered_list_open",
        "fence",
        "blockquote_open",
        "table_open",
        "hr",
        "dl_open",
        "footnote_block_open",
        "html_block",
    } <= types

    inline_types = {child.type for child in inline_children(document)}
    assert {
        "strong_open",
        "em_open",
        "s_open",
        "code_inline",
        "hardbreak",
        "link_open",
        "image",
        "footnote_ref",
        "html_inline",
    } <= inline_types

    levels = {t.tag for t in document.tokens if t.type == "heading_open"}
    assert levels == {f"h{n}" for n in range(1, 7)}


class _FakeStdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
