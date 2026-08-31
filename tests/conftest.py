"""Shared fixtures, and the one environment fix the PDF path needs.

On Apple Silicon, Homebrew installs pango's dylibs into /opt/homebrew/lib,
which is not on the search path of a non-Homebrew interpreter — so ``import
weasyprint`` fails with ``cannot load library 'libgobject-2.0-0'`` even though
pango is correctly installed. Setting the fallback path here rather than in the
shell works because the lookup happens when the library is first opened, not
when the process starts; verified against weasyprint 69.0.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HOMEBREW_LIB = "/opt/homebrew/lib"
FIXTURES = Path(__file__).parent / "fixtures"


def _add_homebrew_to_library_path() -> None:
    if sys.platform != "darwin" or not Path(HOMEBREW_LIB).is_dir():
        return
    current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    entries = current.split(os.pathsep) if current else []
    if HOMEBREW_LIB not in entries:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(
            [*entries, HOMEBREW_LIB]
        )


_add_homebrew_to_library_path()


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
