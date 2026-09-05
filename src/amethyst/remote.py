"""Downloading the images a document points at over the network.

This is the only place in Amethyst that opens a socket, and it runs as a step
of the conversion rather than inside either renderer. That is the whole design:
by the time a renderer sees the token stream, every image it can have is a file
on disk, and neither pipeline needs an opinion about HTTP, a cache, a timeout
or a size limit. The PDF renderer still refuses a remote URL outright — that
refusal is now a backstop for the ones this step could not get, not the policy.

Downloads are cached, keyed by the URL, so converting the same document twice
— or a dozen documents that share a logo — makes one request. The cache is
never invalidated: an image at a URL is treated as the thing that URL names.
Delete the directory to be rid of it.

The limits are deliberately unfriendly. A document is a document, not a
browser: one connection at a time, ten seconds each, thirty-two megabytes at
the outside, and http or https and nothing else — checked again after
redirects, because a redirect is somebody else's choice of scheme.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from amethyst import __version__
from amethyst.document import Document
from amethyst.parse.assets import REMOTE_SCHEMES, Asset, AssetKind
from amethyst.render.base import Warn, discard

#: How long to wait for a response, in seconds. A conversion is interactive:
#: a wait long enough to look like a hang is worse than a missing picture.
TIMEOUT = 10.0

#: The most a single image may be. Past this it is not an illustration, and
#: whatever it is will not lay out on a page anyway.
MAX_BYTES = 32 * 1024 * 1024

#: Read in chunks so that the size limit can be enforced while reading rather
#: than after a refusal has already been held in memory.
CHUNK = 64 * 1024

#: Sent so that a server logging its traffic can see what asked.
USER_AGENT = f"amethyst/{__version__}"

#: Where downloads are kept, under the user's cache directory.
CACHE_PARTS = ("amethyst", "images")

#: The environment variable naming the base cache directory, and the directory
#: to use when it says nothing. Both are the XDG convention, which uv, pip and
#: most of this tool's neighbours already follow on macOS as well as Linux.
CACHE_HOME = "XDG_CACHE_HOME"
DEFAULT_CACHE_HOME = Path.home() / ".cache"

#: Extensions worth trusting from a URL before anything has been fetched. A
#: path ending in something else gets its extension from the response instead.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff"}
)


def cache_directory() -> Path:
    """Where downloaded images are kept between runs."""
    base = os.environ.get(CACHE_HOME)
    root = Path(base) if base else DEFAULT_CACHE_HOME
    return root.joinpath(*CACHE_PARTS)


def fetch_remote_images(
    document: Document,
    *,
    enabled: bool = True,
    warn: Warn = discard,
    cache: Path | None = None,
) -> None:
    """Download the document's remote images and point it at the local copies.

    Rewrites the image tokens in place, exactly as asset resolution rewrites a
    local one, so that a renderer never learns an image was ever remote. An
    image that cannot be fetched is left as written: the renderer then reports
    it missing, naming the URL the author typed.
    """
    references = _remote_images(document)
    if not references or not enabled:
        return

    directory = cache if cache is not None else cache_directory()
    downloaded: dict[str, Path] = {}
    for reference in references:
        path = _download(reference, directory, warn)
        if path is not None:
            downloaded[reference] = path
    if downloaded:
        _rewrite(document, downloaded)


def _remote_images(document: Document) -> list[str]:
    """Every distinct remote image URL, in the order they are written."""
    seen: dict[str, None] = {}
    for asset in document.assets:
        if asset.is_remote and asset.kind is AssetKind.image:
            seen.setdefault(asset.reference, None)
    return list(seen)


def _rewrite(document: Document, downloaded: dict[str, Path]) -> None:
    """Point the tokens, and the recorded assets, at the downloaded files."""
    for token in document.tokens:
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            if child.type != "image":
                continue
            source = child.attrGet("src")
            path = downloaded.get(source) if isinstance(source, str) else None
            if path is not None:
                child.attrSet("src", str(path))
    document.assets = [
        Asset(
            kind=asset.kind,
            reference=asset.reference,
            line=asset.line,
            path=downloaded[asset.reference],
            is_remote=True,
        )
        if asset.is_remote and asset.reference in downloaded
        else asset
        for asset in document.assets
    ]


def _download(url: str, directory: Path, warn: Warn) -> Path | None:
    """Return the local copy of one remote image, fetching it if need be."""
    key = _key(url)
    cached = _cached(directory, key)
    if cached is not None:
        return cached
    try:
        payload, suffix = _read(url)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        warn(f"could not download {url}: {_reason(exc)}.")
        return None
    try:
        return _store(directory, key + suffix, payload)
    except OSError as exc:
        detail = exc.strerror or str(exc)
        warn(f"could not cache {url} in {directory}: {detail.lower()}.")
        return None


def _read(url: str) -> tuple[bytes, str]:
    """Fetch one URL, refusing anything too big or not over http."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT) as response:
        # A redirect is the server's choice of destination, not the author's,
        # so the scheme is checked again on the URL actually opened.
        if urlsplit(response.geturl()).scheme not in REMOTE_SCHEMES:
            raise ValueError("it redirected somewhere that is not http")
        payload = bytearray()
        while chunk := response.read(CHUNK):
            payload += chunk
            if len(payload) > MAX_BYTES:
                raise ValueError(f"it is larger than {MAX_BYTES // (1024 * 1024)}MB")
        suffix = _suffix(url, response.headers.get("Content-Type"))
    return bytes(payload), suffix


def _store(directory: Path, name: str, payload: bytes) -> Path:
    """Write a download into the cache, whole or not at all.

    Written beside the final name and moved onto it, so that a run stopped
    halfway leaves no half a picture for the next one to find and trust.
    """
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    partial = destination.with_name(f"{name}.part{os.getpid()}")
    partial.write_bytes(payload)
    partial.replace(destination)
    return destination


def _cached(directory: Path, key: str) -> Path | None:
    """The cached download for a key, whatever extension it ended up with."""
    if not directory.is_dir():
        return None
    for entry in sorted(directory.glob(f"{key}*")):
        if entry.is_file() and ".part" not in entry.name:
            return entry
    return None


def _key(url: str) -> str:
    """A filename for a URL: its digest, which is stable and has no path in it."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _suffix(url: str, content_type: str | None) -> str:
    """The extension to save a download under.

    Both renderers work out an image's real type from its first bytes, so this
    is for the benefit of anyone who looks in the cache directory — and for
    WeasyPrint, which guesses a MIME type from the name of a ``file:`` URL
    before it falls back to sniffing.
    """
    from_url = Path(unquote(urlsplit(url).path)).suffix.lower()
    if from_url in IMAGE_SUFFIXES:
        return from_url
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return ""


def _reason(exc: BaseException) -> str:
    """Why a download failed, in the words a person would use."""
    if isinstance(exc, HTTPError):
        return f"the server answered {exc.code}"
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "it timed out"
        return str(reason).strip(" <>") or "the request failed"
    if isinstance(exc, TimeoutError):
        return "it timed out"
    if isinstance(exc, OSError):
        return (exc.strerror or str(exc)).lower()
    return str(exc)


__all__ = ["MAX_BYTES", "TIMEOUT", "cache_directory", "fetch_remote_images"]
