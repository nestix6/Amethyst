"""Shared fixtures for the whole suite.

There is deliberately no environment fix-up here. Making Pango reachable on
macOS is the PDF renderer's own job — it repairs the dynamic loader's search
path just before importing WeasyPrint, because the shell export that would
otherwise be needed cannot reach the installed console script. Doing it a
second time here would only hide a regression in the code that ships.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@cache
def _weasyprint_failure() -> str | None:
    """Why the PDF pipeline cannot run here, or ``None`` if it can.

    Goes through the renderer's own import so that whatever it does to make
    the import work is under test rather than assumed. Cached because the
    answer cannot change within a run and the failure path is an expensive
    search through the dynamic loader's directories.
    """
    from amethyst.errors import AmethystError
    from amethyst.render.pdf import import_weasyprint

    try:
        import_weasyprint()
    except AmethystError as exc:
        return exc.message
    return None


@pytest.fixture
def requires_weasyprint() -> None:
    """Skip a test needing the PDF pipeline when WeasyPrint will not load.

    A contributor without Pango installed should still be able to run the
    parse, theme and DOCX tests rather than watch two thirds of the suite fail
    for a reason that has nothing to do with their change.
    """
    failure = _weasyprint_failure()
    if failure is not None:
        pytest.skip(failure)


@pytest.fixture
def fixtures() -> Path:
    """The directory holding the committed test documents."""
    return FIXTURES


@pytest.fixture
def kitchen_sink() -> Path:
    """The document exercising every feature in the support matrix."""
    return FIXTURES / "kitchen-sink.md"


@pytest.fixture
def write_md(tmp_path: Path):
    """Write a Markdown file into a temporary directory and return its path."""

    def _write(name: str, text: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    return _write
