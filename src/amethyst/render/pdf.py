"""HTML to PDF, through WeasyPrint.

Two things here are less obvious than the conversion itself.

WeasyPrint is imported inside the render call, not at module scope. It loads
Pango through cffi, and when that fails it fails with an ``OSError`` naming a
dylib — which is true, and useless. Importing late means the failure lands
where there is enough context to turn it into a sentence the user can act on;
it keeps ``amethyst --help`` working on a machine with no Pango at all; and it
is the one moment at which the search path can still be repaired.

WeasyPrint also reports what it could not do — an image it failed to load, a
declaration it does not support — through the logging module. With no handler
attached those records go to stderr raw, ignoring --quiet and looking like a
crash. They are forwarded through the caller's warning channel instead.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from amethyst.document import Document
from amethyst.errors import MissingDependencyError
from amethyst.parse.assets import REMOTE_SCHEMES
from amethyst.render.base import RenderOptions, RenderResult, Warn
from amethyst.render.html import render_html

#: The logger WeasyPrint reports through, and everything below it.
WEASYPRINT_LOGGER = "weasyprint"

#: What a document is allowed to reference: files beside it, and data URIs it
#: carries itself. Both are already in hand when the conversion starts.
LOCAL_PROTOCOLS = ("file", "data")

#: Where Homebrew puts its dylibs, Apple Silicon first. Checked on disk to tell
#: "Pango is not installed" apart from "Pango is installed but unreachable",
#: which need opposite advice and are indistinguishable from the traceback.
HOMEBREW_LIB_DIRS = (Path("/opt/homebrew/lib"), Path("/usr/local/lib"))

#: The library whose absence WeasyPrint reports first. It is a GLib library
#: rather than Pango itself, which is what makes the raw error so misleading.
PANGO_MARKER = "libgobject-2.0.dylib"

#: The macOS dynamic loader's list of last-resort directories.
DYLD_FALLBACK_PATH = "DYLD_FALLBACK_LIBRARY_PATH"

WEASYPRINT_INSTALL_DOCS = (
    "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html"
)


def render_pdf(document: Document, options: RenderOptions) -> RenderResult:
    """Convert a document to the bytes of a PDF."""
    weasyprint = import_weasyprint()
    html = render_html(document, options)

    with forwarding_warnings(options.warn):
        rendered = weasyprint.HTML(
            string=html,
            # Relative references in the markup resolve against the source
            # file's directory, and so must the absolute paths asset
            # resolution rewrote image sources to — which only works if the
            # base is a file: URL rather than a bare path.
            base_url=document.base_dir.resolve().as_uri() + "/",
            url_fetcher=local_only_fetcher(weasyprint),
        ).render()
        data: bytes = rendered.write_pdf()

    return RenderResult(data=data, pages=len(rendered.pages))


def local_only_fetcher(weasyprint: Any) -> Any:
    """A fetcher that reads local files and never reaches the network.

    Remote images *are* downloaded — by :mod:`amethyst.remote`, as a step of
    the conversion, before any of this runs — and by the time a document
    reaches WeasyPrint every image it can have is a file on disk. So a URL
    arriving here is one that step could not get, or one it was told not to
    fetch with ``--no-remote``, and rendering is the wrong moment to try
    again: there is no cache, no timeout and no size limit down here, and a
    conversion that quietly waits on the network is slow when it works and
    mystifying when it does not. The refusal carries its own wording because
    WeasyPrint's — "URI uses disallowed protocol" — reads like a security
    policy rather than an image that is simply absent. Everything else
    unexpected is refused by protocol.

    Subclassed inside the function because the base class arrives with the
    lazily imported module, and there is nothing to inherit from until then.
    """

    class LocalOnlyFetcher(weasyprint.URLFetcher):  # type: ignore[misc, name-defined]
        def fetch(self, url: str, headers: Any = None) -> Any:
            if urlsplit(url).scheme in REMOTE_SCHEMES:
                raise ValueError("this image was not downloaded")
            return super().fetch(url, headers)

    return LocalOnlyFetcher(allowed_protocols=LOCAL_PROTOCOLS)


@contextmanager
def forwarding_warnings(warn: Warn) -> Iterator[None]:
    """Send WeasyPrint's log through ``warn`` for the duration of a render.

    Adding a handler is also what stops the logging module falling back to its
    last-resort handler, which writes to stderr no matter what the CLI wants.
    """
    logger = logging.getLogger(WEASYPRINT_LOGGER)
    handler = _ForwardingHandler(warn)
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)


class _ForwardingHandler(logging.Handler):
    """A log handler that hands each record's message to a callback."""

    def __init__(self, warn: Warn) -> None:
        super().__init__(level=logging.WARNING)
        self._warn = warn

    def emit(self, record: logging.LogRecord) -> None:
        self._warn(record.getMessage())


def import_weasyprint() -> Any:
    """Import WeasyPrint, or explain in one line why it will not load."""
    _add_homebrew_libraries_to_search_path()
    try:
        # WeasyPrint prints its own installation advice when the dynamic
        # libraries will not open, and prints it to stdout, where a document
        # may be on its way out. It is caught and dropped: the error raised
        # below says the same thing about the machine it is actually running
        # on, which is the more useful half.
        with redirect_stdout(io.StringIO()):
            import weasyprint
    except Exception as exc:  # noqa: BLE001 - the cffi layer raises OSError
        raise _dependency_error(exc) from exc
    return weasyprint


def _add_homebrew_libraries_to_search_path() -> None:
    """Point the dynamic loader at Homebrew's libraries, on macOS.

    Homebrew installs Pango somewhere an interpreter Homebrew did not install
    does not look, so importing WeasyPrint fails naming a dylib even though
    ``brew install pango`` succeeded and the file is right there. The usual
    cure is to export the fallback path in the shell before running the
    command, and for the installed console script that cannot work: the script
    is a ``/bin/sh`` wrapper, and macOS strips every ``DYLD_*`` variable from
    the environment when it executes a system-protected binary like ``sh``.

    Setting the variable here does work, late as it looks. The loader reads it
    when a library is first opened rather than when the process starts, so a
    change made in-process moments before the import still counts.
    """
    if sys.platform != "darwin":
        return
    directory = _installed_pango_dir()
    if directory is None:
        return
    current = os.environ.get(DYLD_FALLBACK_PATH, "")
    entries = current.split(os.pathsep) if current else []
    if str(directory) not in entries:
        os.environ[DYLD_FALLBACK_PATH] = os.pathsep.join([*entries, str(directory)])


def _dependency_error(exc: BaseException) -> MissingDependencyError:
    """Turn an import failure into the advice that actually fixes it.

    The distinction worth making is whether Pango is on the machine at all.
    If it is not, there is one command to run. If it is — and the loader has
    already been pointed at it — then something stranger is wrong, and telling
    someone to install a library they already installed sends them in circles.
    """
    if isinstance(exc, ModuleNotFoundError) and exc.name == "weasyprint":
        return MissingDependencyError(
            "WeasyPrint is not installed, so PDF output is unavailable.",
            hint="Reinstall Amethyst, or convert to DOCX with -f docx.",
        )

    if sys.platform != "darwin":
        return MissingDependencyError(
            "PDF output needs Pango, which could not be loaded.",
            hint=f"Install your system's Pango packages: {WEASYPRINT_INSTALL_DOCS}",
        )

    installed_at = _installed_pango_dir()
    if installed_at is None:
        return MissingDependencyError(
            "PDF output needs Pango, which is not installed.",
            hint="Install it with `brew install pango`.",
        )
    return MissingDependencyError(
        f"Pango is installed in {installed_at}, but WeasyPrint could not load "
        "it from there.",
        hint=(
            "Most often the libraries and this Python are built for different "
            "architectures — check that `brew config` and this Python agree "
            "on arm64 against x86_64."
        ),
    )


def _installed_pango_dir() -> Path | None:
    """The Homebrew lib directory holding Pango's GLib dependency, if any."""
    for directory in HOMEBREW_LIB_DIRS:
        if (directory / PANGO_MARKER).exists():
            return directory
    return None
