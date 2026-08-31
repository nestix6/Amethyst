"""Resolution of the files a document points at.

Markdown says ``![](diagram.png)`` and means "next to this file". Both
renderers need that turned into something they can open — WeasyPrint fetches a
URL, python-docx opens a path — and resolving it once, here, is what stops the
two from disagreeing about where the file was.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it.token import Token

#: Schemes that name something to be fetched over the network. Anything else
#: with a scheme (``data:``, ``mailto:``, ``file:``) needs no resolving and is
#: passed through to the renderer exactly as written.
REMOTE_SCHEMES = frozenset({"http", "https"})


class AssetKind(str, Enum):
    """What the reference was written as. The value doubles as its noun."""

    image = "image"
    link = "link"


@dataclass(frozen=True)
class Asset:
    """One outward reference from the document, and where it landed."""

    kind: AssetKind
    #: The target exactly as written in the Markdown, for error messages.
    reference: str
    #: 1-based line in the source file, or ``None`` if the token carried no map.
    line: int | None = None
    #: The local file the reference resolves to, or ``None`` if it is not one.
    path: Path | None = None
    is_remote: bool = False

    @property
    def is_missing(self) -> bool:
        """True for a local reference with no file at the resolved path."""
        return self.path is not None and not self.path.is_file()


def resolve_assets(tokens: list[Token], base_dir: Path) -> list[Asset]:
    """Resolve local references against ``base_dir`` and rewrite image sources.

    An image whose source names a local file that exists is rewritten in place
    to an absolute path, which is what both renderers want. Everything else —
    remote URLs, data URIs, files that are not there — is left exactly as the
    author typed it, so the eventual error names their reference rather than
    one this function invented.

    Returns every reference worth knowing about later: images of all kinds, and
    links that point at a local file. Bare fragments (``#section``) and
    ``mailto:`` links resolve to nothing and are left out.
    """
    assets: list[Asset] = []
    for token in tokens:
        if token.type != "inline" or not token.children:
            continue
        line = token.map[0] + 1 if token.map else None
        for child in token.children:
            if child.type == "image":
                asset = _resolve(AssetKind.image, child.attrGet("src"), base_dir, line)
                if asset is None:
                    continue
                assets.append(asset)
                if asset.path is not None and not asset.is_missing:
                    child.attrSet("src", str(asset.path))
            elif child.type == "link_open":
                asset = _resolve(AssetKind.link, child.attrGet("href"), base_dir, line)
                # Links are recorded, never rewritten: an absolute filesystem
                # path in an href would be a worse link than the relative one.
                if asset is not None and asset.path is not None:
                    assets.append(asset)
    return assets


def _resolve(
    kind: AssetKind, reference: object, base_dir: Path, line: int | None
) -> Asset | None:
    """Classify one reference, and locate it if it names a local file."""
    if not isinstance(reference, str) or not reference:
        return None

    parts = urlsplit(reference)
    if parts.scheme or parts.netloc:
        if parts.scheme not in REMOTE_SCHEMES:
            return None
        return Asset(kind, reference, line, is_remote=True)

    # Strip the fragment and query the URL syntax allows, then undo the
    # percent-encoding: `my%20image.png` on the page is `my image.png` on disk.
    target = unquote(parts.path)
    if not target:
        return None

    candidate = Path(target)
    resolved = candidate if candidate.is_absolute() else base_dir / candidate
    return Asset(kind, reference, line, path=resolved.resolve())
