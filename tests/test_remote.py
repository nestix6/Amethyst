"""Downloading remote images: the cache, the limits, and what a failure does.

Nothing here opens a socket. The suite's ``offline`` fixture makes ``urlopen``
raise, and every test that means to fetch something puts a fake in its place —
which is also the only way to test a timeout, a redirect and a thirty-megabyte
image without arranging for one to exist.
"""

from __future__ import annotations

import io
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from amethyst.document import Document
from amethyst.remote import MAX_BYTES, cache_directory, fetch_remote_images

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

DOC = "![a picture](https://example.com/pic.png)\n"


class FakeResponse(io.BytesIO):
    """Just enough of what ``urlopen`` returns for the fetcher to read it."""

    def __init__(self, payload: bytes, *, url: str, content_type: str | None = None):
        super().__init__(payload)
        self._url = url
        self.headers = {"Content-Type": content_type} if content_type else {}

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def server(monkeypatch):
    """Answer every request with one payload, and count the requests."""

    def install(
        payload=PNG,
        *,
        url="https://example.com/pic.png",
        content_type=None,
        error: Exception | None = None,
    ):
        calls: list[str] = []

        def urlopen(request, timeout=None):
            calls.append(getattr(request, "full_url", request))
            if error is not None:
                raise error
            return FakeResponse(payload, url=url, content_type=content_type)

        monkeypatch.setattr("amethyst.remote.urlopen", urlopen)
        return calls

    return install


@pytest.fixture
def document(tmp_path) -> Document:
    return Document.from_markdown(DOC, base_dir=tmp_path)


def sources(document: Document) -> list[str]:
    """Every image source in the token stream, after any rewriting."""
    return [
        child.attrGet("src")
        for token in document.tokens
        if token.type == "inline" and token.children
        for child in token.children
        if child.type == "image"
    ]


# --- the happy path -------------------------------------------------------


def test_a_downloaded_image_becomes_a_local_file(document, server, tmp_path):
    calls = server()
    fetch_remote_images(document, cache=tmp_path / "cache")
    (source,) = sources(document)
    assert calls == ["https://example.com/pic.png"]
    assert Path(source).is_file()
    assert Path(source).read_bytes() == PNG


def test_the_recorded_asset_points_at_the_download_too(document, server, tmp_path):
    """`missing_assets` would otherwise still call a fetched image missing."""
    server()
    fetch_remote_images(document, cache=tmp_path / "cache")
    (asset,) = document.assets
    assert asset.is_remote and asset.path is not None
    assert not asset.is_missing
    assert document.missing_assets == []


def test_the_extension_comes_from_the_url_then_the_content_type(
    tmp_path, server, monkeypatch
):
    for markdown, content_type, expected in (
        ("![a](https://example.com/pic.png)\n", None, ".png"),
        ("![a](https://example.com/render?id=7)\n", "image/gif", ".gif"),
        ("![a](https://example.com/render?id=8)\n", None, ""),
    ):
        document = Document.from_markdown(markdown, base_dir=tmp_path)
        server(url=markdown[markdown.index("(") + 1 : -2], content_type=content_type)
        fetch_remote_images(document, cache=tmp_path / "cache")
        (source,) = sources(document)
        assert Path(source).suffix == expected


# --- the cache ------------------------------------------------------------


def test_a_second_conversion_uses_the_cache(document, server, tmp_path):
    cache = tmp_path / "cache"
    calls = server()
    fetch_remote_images(document, cache=cache)
    again = Document.from_markdown(DOC, base_dir=tmp_path)
    fetch_remote_images(again, cache=cache)
    assert len(calls) == 1
    assert sources(document) == sources(again)


def test_one_url_twice_in_a_document_is_fetched_once(tmp_path, server):
    document = Document.from_markdown(DOC + "\n" + DOC, base_dir=tmp_path)
    calls = server()
    fetch_remote_images(document, cache=tmp_path / "cache")
    assert len(calls) == 1
    assert len(set(sources(document))) == 1


def test_a_half_written_download_is_not_left_where_a_run_would_trust_it(
    document, server, tmp_path
):
    cache = tmp_path / "cache"
    server()
    fetch_remote_images(document, cache=cache)
    assert [path.name for path in cache.iterdir() if ".part" in path.name] == []


def test_the_cache_directory_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache_directory() == tmp_path / "amethyst" / "images"


# --- what a failure does --------------------------------------------------


def warnings_for(document, tmp_path, **kwargs) -> list[str]:
    messages: list[str] = []
    fetch_remote_images(
        document, warn=messages.append, cache=tmp_path / "cache", **kwargs
    )
    return messages


def test_a_server_error_warns_and_leaves_the_reference_alone(
    document, server, tmp_path
):
    server(error=HTTPError("https://example.com/pic.png", 404, "Not Found", {}, None))
    messages = warnings_for(document, tmp_path)
    assert any("the server answered 404" in message for message in messages)
    assert sources(document) == ["https://example.com/pic.png"]


def test_a_refused_connection_warns_in_words(document, server, tmp_path):
    server(error=URLError("Connection refused"))
    (message,) = warnings_for(document, tmp_path)
    assert "could not download" in message and "Connection refused" in message


def test_a_timeout_says_so(document, server, tmp_path):
    server(error=TimeoutError())
    (message,) = warnings_for(document, tmp_path)
    assert "timed out" in message


def test_an_enormous_image_is_refused_while_it_is_read(document, server, tmp_path):
    server(payload=b"0" * (MAX_BYTES + 1))
    (message,) = warnings_for(document, tmp_path)
    assert "larger than" in message
    assert sources(document) == ["https://example.com/pic.png"]


def test_a_redirect_off_the_web_is_refused(document, server, tmp_path):
    """Where a redirect lands is the server's choice, so it is checked again."""
    server(url="ftp://example.com/pic.png")
    (message,) = warnings_for(document, tmp_path)
    assert "redirected" in message


# --- being told not to ----------------------------------------------------


def test_no_remote_makes_no_request_at_all(document, tmp_path):
    """The suite's offline fixture is the assertion: urlopen would raise."""
    assert warnings_for(document, tmp_path, enabled=False) == []
    assert sources(document) == ["https://example.com/pic.png"]


def test_a_document_with_no_remote_images_touches_nothing(tmp_path):
    document = Document.from_markdown("![a](local.png)\n", base_dir=tmp_path)
    fetch_remote_images(document, cache=tmp_path / "cache")
    assert not (tmp_path / "cache").exists()


def test_a_remote_link_is_not_an_image_and_is_not_fetched(tmp_path):
    document = Document.from_markdown(
        "[a](https://example.com/page)\n", base_dir=tmp_path
    )
    fetch_remote_images(document, cache=tmp_path / "cache")
    assert not (tmp_path / "cache").exists()
