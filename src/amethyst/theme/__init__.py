"""The theme layer: one declaration of fonts, scale, colour and page geometry.

The ``Theme`` dataclass and its two compilers — one to CSS, one to Word styles
— belong here; the whole point of the package is that PDF and DOCX read the
same declaration. Today it owns one thing: ``builtin/css/base.css``, the
structural stylesheet the PDF pipeline is built on. Generated theme variables
will sit in front of that file rather than replace it, so it is written to
stand on its own.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files

#: Location of the structural stylesheet inside this package. It is package
#: data, not a file next to the source: an installed wheel has no source tree,
#: and reading it any other way works in a checkout and fails once shipped.
BASE_CSS_PARTS = ("builtin", "css", "base.css")


@cache
def base_css() -> str:
    """Return the structural stylesheet every PDF is built on."""
    resource = files(__name__)
    for part in BASE_CSS_PARTS:
        resource = resource / part
    return resource.read_text(encoding="utf-8")


__all__ = ["base_css"]
