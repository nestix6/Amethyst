"""The theme layer: one declaration of fonts, scale, colour and page geometry.

A theme is what keeps the two output formats looking like the same document.
It is a small TOML file, and it compiles two ways: to the CSS custom properties
``base.css`` reads, and — once the Word renderer lands — to a set of Word style
definitions. Neither renderer holds an opinion about a font or a colour.

Anything a theme leaves out is filled in from the builtin ``default``, so a
custom theme can be three lines that change the accent colour and nothing else.
That also means every ``Theme`` is complete by construction, and a renderer
never has to ask whether a value is there.

Sizes are declared as bare numbers rather than CSS lengths on purpose. The two
that are absolute — the body and small text sizes — are points, because that is
what print measures in and what Word wants; everything else is a multiple of
the body size, so a theme scales as a whole and neither compiler has to parse a
unit out of a string.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from amethyst.errors import ThemeError, UsageError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 only
    import tomli as tomllib

#: Location of the structural stylesheet inside this package. It is package
#: data, not a file next to the source: an installed wheel has no source tree,
#: and reading it any other way works in a checkout and fails once shipped.
BASE_CSS_PARTS = ("builtin", "css", "base.css")

#: Where the builtin themes live, inside this package.
BUILTIN_DIR = "builtin"

#: The theme every other one is completed from, and the one used when the user
#: names none.
DEFAULT_THEME = "default"

#: Heading levels a theme declares a size for: h1 through h6, no more, no less.
HEADING_LEVELS = 6

#: Colours are hex, three or six digits. Nothing else: the CSS side would take
#: any colour notation going, but a Word style needs three bytes, and a theme
#: that renders in one format and not the other is the failure this whole layer
#: exists to prevent.
HEX_COLOR = re.compile(r"\A#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")

#: Characters that would end a declaration or open a block, and so turn a bad
#: value into a broken stylesheet rather than an error message.
CSS_UNSAFE = re.compile(r"[;{}<>\"'\\]|/\*")


@dataclass(frozen=True)
class Fonts:
    """Three font stacks, most-preferred family first."""

    body: tuple[str, ...]
    heading: tuple[str, ...]
    mono: tuple[str, ...]


@dataclass(frozen=True)
class Type:
    """The type scale: two absolute sizes in points, the rest relative."""

    #: Body text size, in points.
    size: float
    #: Footnotes, table cells and page furniture, in points.
    small: float
    #: Line height, as a multiple of the font size.
    line_height: float
    #: CSS font weight for headings, 100–900.
    heading_weight: int
    #: h1–h6, as multiples of the body size.
    headings: tuple[float, ...]


@dataclass(frozen=True)
class Colors:
    """The palette, as six-digit hex."""

    text: str
    muted: str
    accent: str
    rule: str
    fill: str


@dataclass(frozen=True)
class Spacing:
    """Vertical and horizontal rhythm, as multiples of the body size."""

    #: Gap after a paragraph, list, table or code block.
    block: float
    #: How far a list or a definition is indented.
    indent: float


@dataclass(frozen=True)
class Page:
    """Sheet geometry. Both are CSS, because both are paged-media descriptors."""

    size: str
    margin: str


@dataclass(frozen=True)
class Theme:
    """One complete declaration of how a document should look."""

    name: str
    description: str
    fonts: Fonts
    type: Type
    colors: Colors
    spacing: Spacing
    page: Page

    def with_page(self, *, size: str | None = None, margin: str | None = None) -> Theme:
        """Return this theme with the page geometry a flag overrode.

        ``None`` means the flag was not passed, which leaves the theme's own
        value in place. This is the only way page geometry is overridden, so
        there is exactly one place a renderer has to look for it.
        """
        if size is None and margin is None:
            return self
        page = Page(size=size or self.page.size, margin=margin or self.page.margin)
        return replace(self, page=page)


@cache
def base_css() -> str:
    """Return the structural stylesheet every PDF is built on."""
    resource = files(__name__)
    for part in BASE_CSS_PARTS:
        resource = resource / part
    return resource.read_text(encoding="utf-8")


@cache
def builtin_names() -> tuple[str, ...]:
    """The names of the themes shipped inside the package, sorted."""
    directory = files(__name__) / BUILTIN_DIR
    return tuple(
        sorted(
            entry.name.removesuffix(".toml")
            for entry in directory.iterdir()
            if entry.name.endswith(".toml")
        )
    )


def locate_theme(source: str) -> str:
    """Check that a theme is there, returning it as given.

    Only existence is settled here. A name that is not a builtin, or a path
    with no file at it, is a mistyped invocation and raises ``UsageError``; a
    theme that is found but will not parse raises ``ThemeError`` when it is
    read. The two are different mistakes and get different exit codes.
    """
    if _is_path(source):
        if not Path(source).is_file():
            raise UsageError(f"No theme file at {source}.")
        return source
    names = builtin_names()
    if source not in names:
        raise UsageError(
            f"Unknown theme {source!r}.",
            hint=f"Builtin themes: {', '.join(names)}.",
        )
    return source


def read_theme_text(source: str) -> str:
    """Return a theme's TOML as written, for showing or copying."""
    locate_theme(source)
    if _is_path(source):
        return _read_file(Path(source))
    return _read_builtin(source)


def load_theme(source: str) -> Theme:
    """Load a theme by builtin name or path, filling in what it leaves out."""
    text = read_theme_text(source)
    data = _parse(text, source)
    _reject_unknown(data, source)
    merged = _merge(_default_sections(), data)
    return _build(
        merged,
        name=Path(source).stem,
        description=_description(data, source),
        source=source,
    )


@cache
def default_theme() -> Theme:
    """The theme a document gets when the user names none."""
    return load_theme(DEFAULT_THEME)


# --- locating and reading -------------------------------------------------


def _is_path(source: str) -> bool:
    """Whether a theme was named as a file rather than as a builtin.

    A bare word is a builtin name; anything carrying a directory or a ``.toml``
    extension is a path. Written out so the check that a theme exists and the
    read that follows it can never disagree about which one they are doing.
    """
    candidate = Path(source)
    return candidate.suffix.lower() == ".toml" or candidate.parent != Path(".")


def _read_file(path: Path) -> str:
    """Read a theme file, reporting a failure as one line rather than a trace."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or "it is not valid UTF-8 text"
        raise ThemeError(
            f"Could not read the theme at {path}: {detail.lower()}."
        ) from exc


def _read_builtin(name: str) -> str:
    """Read a builtin theme out of the package's data."""
    resource = files(__name__) / BUILTIN_DIR / f"{name}.toml"
    return resource.read_text(encoding="utf-8")


def _parse(text: str, source: str) -> dict[str, Any]:
    """Parse a theme's TOML, naming the line when it will not parse."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ThemeError(f"{source} is not valid TOML: {exc}.") from exc


@cache
def _default_sections() -> dict[str, dict[str, Any]]:
    """The default theme's settings — which are also the schema.

    Every setting a theme may declare is one this file declares, so validating
    a theme against it needs no second statement of what the settings are, and
    adding one to the default file is the whole of adding one to the format.

    ``description`` is left out: it is the only top-level key, and it is the
    one thing a theme does not inherit. A custom theme that says nothing about
    itself should say nothing, not describe the default.
    """
    data = _parse(_read_builtin(DEFAULT_THEME), DEFAULT_THEME)
    return {key: value for key, value in data.items() if isinstance(value, dict)}


# --- validation -----------------------------------------------------------


def _reject_unknown(data: dict[str, Any], source: str) -> None:
    """Refuse a setting that does not exist, rather than silently ignoring it.

    A theme is edited by hand and looked at afterwards. A misspelled key that
    is quietly dropped looks exactly like a theme that does not work, which is
    a much worse afternoon than being told which line is wrong.
    """
    defaults = _default_sections()
    sections = ", ".join(defaults)
    for key, value in data.items():
        if key == "description":
            continue
        if key not in defaults:
            raise ThemeError(
                f"{source}: unknown section [{key}].",
                hint=f"A theme declares: {sections}.",
            )
        if not isinstance(value, dict):
            raise ThemeError(f"{source}: [{key}] must be a table of settings.")
        for name in value:
            if name not in defaults[key]:
                known = ", ".join(defaults[key])
                raise ThemeError(
                    f"{source}: unknown setting {name!r} in [{key}].",
                    hint=f"[{key}] takes: {known}.",
                )


def _merge(
    defaults: dict[str, dict[str, Any]], data: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Lay a theme over the defaults, one section at a time."""
    return {
        section: {**values, **data.get(section, {})}
        for section, values in defaults.items()
    }


def _description(data: dict[str, Any], source: str) -> str:
    """A theme's own one-line description, which is never inherited."""
    value = data.get("description", "")
    if not isinstance(value, str):
        raise ThemeError(f"{source}: description must be text.")
    return value.strip()


def _build(
    data: dict[str, dict[str, Any]], *, name: str, description: str, source: str
) -> Theme:
    """Turn merged data into a validated theme."""
    return Theme(
        name=name,
        description=description,
        fonts=Fonts(
            body=_families(data, "fonts", "body", source),
            heading=_families(data, "fonts", "heading", source),
            mono=_families(data, "fonts", "mono", source),
        ),
        type=Type(
            size=_positive(data, "type", "size", source),
            small=_positive(data, "type", "small", source),
            line_height=_positive(data, "type", "line_height", source),
            heading_weight=_weight(data, "type", "heading_weight", source),
            headings=_scale(data, "type", "headings", source),
        ),
        colors=Colors(
            text=_color(data, "colors", "text", source),
            muted=_color(data, "colors", "muted", source),
            accent=_color(data, "colors", "accent", source),
            rule=_color(data, "colors", "rule", source),
            fill=_color(data, "colors", "fill", source),
        ),
        spacing=Spacing(
            block=_positive(data, "spacing", "block", source),
            indent=_positive(data, "spacing", "indent", source),
        ),
        page=Page(
            size=_css(data, "page", "size", source),
            margin=_css(data, "page", "margin", source),
        ),
    )


def _value(data: dict[str, dict[str, Any]], section: str, key: str, source: str) -> Any:
    """One setting, after the merge — so an absence is a broken default file."""
    try:
        return data[section][key]
    except KeyError:
        raise ThemeError(f"{source}: [{section}] has no {key!r}.") from None


def _invalid(section: str, key: str, source: str, must: str, value: Any) -> ThemeError:
    """The one shape every validation failure is reported in."""
    return ThemeError(f"{source}: {section}.{key} must be {must}, not {value!r}.")


def _number(value: Any) -> float | None:
    """A TOML number as a float, or ``None``. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _positive(
    data: dict[str, dict[str, Any]], section: str, key: str, source: str
) -> float:
    value = _value(data, section, key, source)
    number = _number(value)
    if number is None or number <= 0:
        raise _invalid(section, key, source, "a positive number", value)
    return number


def _weight(
    data: dict[str, dict[str, Any]], section: str, key: str, source: str
) -> int:
    value = _value(data, section, key, source)
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 900:
        raise _invalid(section, key, source, "a font weight from 100 to 900", value)
    return value


def _scale(
    data: dict[str, dict[str, Any]], section: str, key: str, source: str
) -> tuple[float, ...]:
    value = _value(data, section, key, source)
    must = f"a list of {HEADING_LEVELS} positive numbers, h1 first"
    if not isinstance(value, list) or len(value) != HEADING_LEVELS:
        raise _invalid(section, key, source, must, value)
    sizes = [_number(item) for item in value]
    if any(size is None or size <= 0 for size in sizes):
        raise _invalid(section, key, source, must, value)
    return tuple(size for size in sizes if size is not None)


def _color(data: dict[str, dict[str, Any]], section: str, key: str, source: str) -> str:
    value = _value(data, section, key, source)
    if not isinstance(value, str) or not HEX_COLOR.match(value):
        raise _invalid(section, key, source, 'a hex colour like "#6a3fa0"', value)
    digits = value.lstrip("#").lower()
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return f"#{digits}"


def _families(
    data: dict[str, dict[str, Any]], section: str, key: str, source: str
) -> tuple[str, ...]:
    value = _value(data, section, key, source)
    must = "a list of font family names"
    if not isinstance(value, list) or not value:
        raise _invalid(section, key, source, must, value)
    for family in value:
        if not isinstance(family, str) or not family.strip():
            raise _invalid(section, key, source, must, value)
        if CSS_UNSAFE.search(family):
            raise _invalid(section, key, source, "a plain font family name", family)
    return tuple(family.strip() for family in value)


def _css(data: dict[str, dict[str, Any]], section: str, key: str, source: str) -> str:
    """A value written straight into the stylesheet, so checked before it is."""
    value = _value(data, section, key, source)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(section, key, source, "a CSS value", value)
    if CSS_UNSAFE.search(value):
        raise _invalid(section, key, source, "a single CSS value", value)
    return value.strip()


__all__ = [
    "DEFAULT_THEME",
    "HEADING_LEVELS",
    "Colors",
    "Fonts",
    "Page",
    "Spacing",
    "Theme",
    "Type",
    "base_css",
    "builtin_names",
    "default_theme",
    "load_theme",
    "locate_theme",
    "read_theme_text",
]
