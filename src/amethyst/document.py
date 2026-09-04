"""The parsed document: its metadata, its tokens, and where it came from.

This is the only object the renderers are given. It carries the source
directory rather than the source file because that is what a relative image
path resolves against, and stdin has the second without having the first.
"""

from __future__ import annotations

import datetime
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markdown_it.token import Token

from amethyst.errors import InputError
from amethyst.parse.assets import Asset, resolve_assets
from amethyst.parse.frontmatter import split_frontmatter
from amethyst.parse.markdown import build_parser


@dataclass(frozen=True)
class Heading:
    """One heading, as the contents and the running head see it."""

    #: 1 for ``h1``, 6 for ``h6``.
    level: int
    #: The heading's visible text, with the markup flattened out of it.
    text: str
    #: The HTML id the anchors plugin gave it, which is what a contents entry
    #: links to and what a Word bookmark is named after. ``None`` only if the
    #: parser ever stops assigning one, in which case the entry is still
    #: listed — unlinked, and without a page number.
    anchor: str | None = None


@dataclass
class Document:
    """A Markdown file, parsed and ready to render."""

    #: The token stream, with the frontmatter token removed and local image
    #: sources rewritten to absolute paths.
    tokens: list[Token]
    #: Frontmatter fields, keys lowercased, values as YAML produced them.
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Every reference out of the document — see :func:`resolve_assets`.
    assets: list[Asset] = field(default_factory=list)
    #: The file this came from, or ``None`` when it was read from stdin.
    source: Path | None = None
    #: What relative paths resolve against: the source's directory, or the
    #: working directory for stdin.
    base_dir: Path = field(default_factory=Path.cwd)
    #: The original Markdown, frontmatter included.
    text: str = ""

    @classmethod
    def from_markdown(
        cls,
        text: str,
        *,
        source: Path | None = None,
        base_dir: Path | None = None,
    ) -> Document:
        """Parse Markdown text into a document.

        ``base_dir`` defaults to the source file's directory, and to the
        working directory when there is no source file.
        """
        if base_dir is None:
            base_dir = source.resolve().parent if source is not None else Path.cwd()

        metadata, tokens = split_frontmatter(build_parser().parse(text))
        assets = resolve_assets(tokens, base_dir)
        return cls(
            tokens=tokens,
            metadata=metadata,
            assets=assets,
            source=source,
            base_dir=base_dir,
            text=text,
        )

    @property
    def title(self) -> str | None:
        """The frontmatter title, or failing that the first level-1 heading."""
        declared = _as_text(self.metadata.get("title"))
        if declared is not None:
            return declared
        first = next((item for item in self.headings if item.level == 1), None)
        return (first.text or None) if first is not None else None

    @property
    def subtitle(self) -> str | None:
        """The declared subtitle. It reaches the title page and the metadata."""
        return _as_text(self.metadata.get("subtitle"))

    @property
    def author(self) -> str | None:
        """The declared author. A YAML list becomes a comma-separated string."""
        return _as_text(self.metadata.get("author"))

    @property
    def date(self) -> str | None:
        """The declared date, as text. YAML dates arrive parsed; ISO them back."""
        return _as_text(self.metadata.get("date"))

    @property
    def keywords(self) -> str | None:
        """The declared keywords, comma-separated — which both formats want."""
        return _as_text(self.metadata.get("keywords"))

    @property
    def created(self) -> datetime.date | None:
        """The declared date as a real date, or ``None`` if it is not one.

        A document may be dated "Spring 2026", which belongs on a title page
        and nowhere near a file's creation timestamp. Only a date that parses
        reaches the PDF's and Word's metadata; the rest stays text.
        """
        text = self.date
        if text is None:
            return None
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return None

    @property
    def headings(self) -> list[Heading]:
        """Every heading in the document, in the order they are written.

        Derived from the tokens rather than collected during the parse: the
        contents, the running head and Word's bookmarks all want the same
        list, and there is nothing here that the token stream does not already
        say.
        """
        found: list[Heading] = []
        for index, token in enumerate(self.tokens):
            if token.type != "heading_open":
                continue
            inline = self.tokens[index + 1] if index + 1 < len(self.tokens) else None
            if inline is None or inline.type != "inline":
                continue
            anchor = token.attrGet("id")
            found.append(
                Heading(
                    level=int(token.tag[1:]),
                    text=_inline_text(inline),
                    anchor=anchor if isinstance(anchor, str) and anchor else None,
                )
            )
        return found

    @property
    def missing_assets(self) -> list[Asset]:
        """Local references with no file at the other end."""
        return [asset for asset in self.assets if asset.is_missing]


def load_document(source: Path | None) -> Document:
    """Read Markdown from a file, or from stdin when ``source`` is ``None``."""
    if source is None:
        return Document.from_markdown(_read_stdin(), base_dir=Path.cwd())
    return Document.from_markdown(_read_file(source), source=source)


def _read_file(source: Path) -> str:
    """Read a Markdown file as UTF-8, reporting failures as one clear line."""
    try:
        # utf-8-sig so a byte-order mark from a Windows editor does not end up
        # as an invisible first character of the first heading.
        return source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(
            f"{source} is not valid UTF-8 text.",
            hint="Amethyst reads UTF-8 Markdown; convert the file first.",
        ) from exc
    except FileNotFoundError as exc:
        raise InputError(f"No such file: {source}.") from exc
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise InputError(f"Could not read {source}: {detail.lower()}.") from exc


def _read_stdin() -> str:
    """Read the whole of stdin as the document."""
    try:
        return sys.stdin.read()
    except UnicodeDecodeError as exc:
        raise InputError(
            "The Markdown on stdin is not valid UTF-8 text.",
            hint="Amethyst reads UTF-8 Markdown; convert the input first.",
        ) from exc


def _inline_text(token: Token) -> str:
    """Flatten an inline token to its visible text, dropping the markup."""
    if not token.children:
        return token.content.strip()
    parts = [
        child.content
        for child in token.children
        if child.type in {"text", "code_inline"}
    ]
    return "".join(parts).strip()


def _as_text(value: Any) -> str | None:
    """Render a metadata value as a display string, or ``None`` if it is empty.

    Frontmatter is YAML, so a value can arrive as a date, a number, a boolean
    or a list. Everything that reaches a title page or a Word core property has
    to be a string, and this is the single place that conversion happens.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime.date):  # covers datetime, which subclasses it
        return value.isoformat()
    if isinstance(value, list | tuple):
        joined = ", ".join(text for text in map(_as_text, value) if text)
        return joined or None
    return str(value)
