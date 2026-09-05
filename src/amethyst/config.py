"""Settings that come from somewhere other than the command line.

A conversion is described in four places, and they are read in this order,
each one overriding the last:

1. the defaults declared below,
2. ``~/.config/amethyst/config.toml`` — how this person's documents look,
3. ``./amethyst.toml`` — how *these* documents look,
4. the document's own frontmatter,
5. the flags on the command line.

That order is the useful one: the further a statement is from the document, the
more general it is, and the thing said closest to the moment of conversion is
the thing that wins.

The tuple of :class:`Setting` below is the whole schema. It is what validates a
file, what rejects a misspelled key, and what ``amethyst init`` writes out with
its defaults — so adding a setting is adding one entry there and reading it in
:func:`_build`, and there is nowhere for a second, disagreeing list to hide.
That is deliberately the same shape the theme layer uses, where
``default.toml`` is both the defaults and the schema.

Two things do not come from here. The input path and the output path are
arguments rather than settings: a file that named them would convert the same
document however it was invoked. And the *format* can be set by a config file
but not by frontmatter — a document may reasonably say how it should look, but
where its output goes is the invocation's business, and reading it from the
document would mean parsing the document before the CLI could tell the user
they forgot ``-o``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amethyst.errors import ConfigError
from amethyst.render.furniture import MAX_TOC_DEPTH
from amethyst.theme import is_theme_path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 only
    import tomli as tomllib

#: The config file a directory of documents carries, and the one ``init``
#: writes.
CONFIG_FILENAME = "amethyst.toml"

#: The per-user config file, under the base directory named by the XDG
#: convention — which is what uv, pip and most of this tool's neighbours
#: already follow on macOS as well as on Linux.
USER_CONFIG_PARTS = ("amethyst", "config.toml")
CONFIG_HOME = "XDG_CONFIG_HOME"
DEFAULT_CONFIG_HOME = Path.home() / ".config"

#: What a document's frontmatter may say about its own conversion. Everything
#: else in the frontmatter is metadata — a title, an author, a date — and is
#: left alone, which is why frontmatter cannot be checked for unknown keys the
#: way a config file can.
FRONTMATTER = "the document's frontmatter"


@dataclass(frozen=True)
class Setting:
    """One thing that can be said in a config file or in frontmatter."""

    name: str
    #: ``str``, ``bool`` or ``int``. A value of another type is refused rather
    #: than coerced: a page size written as a number is a mistake, not a size.
    kind: type
    default: Any
    #: The one-line explanation ``amethyst init`` writes above the key.
    help: str
    #: Values a string setting may take, when there are only a few of them.
    choices: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None
    #: When set, whether a value names a file — and so should be resolved
    #: against the directory of whatever declared it rather than the working
    #: directory. A predicate rather than a flag because the two settings that
    #: take a path do not agree on what one looks like: a stylesheet is always
    #: a file, and a bare word naming a theme is a builtin.
    locate: Callable[[str], bool] | None = None
    #: Whether a document may set this about itself.
    frontmatter: bool = True
    #: What ``init`` shows for a setting whose default is "say nothing".
    example: str | None = None


SETTINGS: tuple[Setting, ...] = (
    Setting(
        "format",
        str,
        None,
        "Output format when the output path does not imply one.",
        choices=("pdf", "docx"),
        frontmatter=False,
        example='"pdf"',
    ),
    Setting(
        "theme",
        str,
        "default",
        "Builtin theme name, or a path to a theme .toml.",
        locate=is_theme_path,
    ),
    Setting(
        "css",
        str,
        None,
        "Extra stylesheet, appended after everything else. PDF only.",
        locate=lambda _value: True,
        example='"house-style.css"',
    ),
    Setting("toc", bool, False, "Open the document with a table of contents."),
    Setting(
        "toc_depth",
        int,
        3,
        "Heading levels the contents lists.",
        minimum=1,
        maximum=MAX_TOC_DEPTH,
    ),
    Setting(
        "title_page", bool, False, "Open with a title page built from frontmatter."
    ),
    Setting(
        "page_size",
        str,
        None,
        "Sheet size, overriding the theme's. A4, Letter, or a CSS size.",
        example='"A4"',
    ),
    Setting(
        "margin",
        str,
        None,
        "Page margin, overriding the theme's. CSS style: 2cm, or 2cm 2.5cm.",
        example='"2cm"',
    ),
    Setting("page_numbers", bool, True, "Number the pages in the footer."),
    Setting(
        "highlight_style",
        str,
        "default",
        "Pygments style for code, or none to leave code uncoloured.",
    ),
    Setting("remote", bool, True, "Download images the document links to."),
)

_BY_NAME = {setting.name: setting for setting in SETTINGS}


@dataclass(frozen=True)
class Settings:
    """Everything the conversion was told, from wherever it was told it."""

    format: str | None
    theme: str
    css: str | None
    toc: bool
    toc_depth: int
    title_page: bool
    page_size: str | None
    margin: str | None
    page_numbers: bool
    highlight_style: str
    remote: bool


def config_files(*, project_dir: Path | None = None) -> list[Path]:
    """The config files that exist, in the order they are read."""
    directory = Path.cwd() if project_dir is None else project_dir
    candidates = [user_config_path(), directory / CONFIG_FILENAME]
    return [path for path in candidates if path.is_file()]


def user_config_path() -> Path:
    """Where this user's own config file lives, whether or not it is there."""
    base = _env(CONFIG_HOME)
    root = Path(base) if base else DEFAULT_CONFIG_HOME
    return root.joinpath(*USER_CONFIG_PARTS)


def read_config_files(files: Sequence[Path] | None = None) -> dict[str, Any]:
    """Everything the config files say, merged, later file winning.

    Kept apart from :func:`resolve_settings` because the CLI has to settle the
    output format before it has read the document — and then settle everything
    else after, once the frontmatter is in hand. Reading the files once and
    merging twice is the difference between that and parsing them twice.
    """
    values: dict[str, Any] = {}
    for path in files if files is not None else config_files():
        values.update(read_config(path))
    return values


def resolve_settings(
    *,
    declared: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    document_dir: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Merge every source of settings into one answer.

    ``declared`` is what the config files said, from :func:`read_config_files`;
    passing nothing reads them. ``overrides`` is what the command line actually
    said — only the flags that were passed, so that a flag left alone does not
    silently overrule a config file with its own default.
    """
    values: dict[str, Any] = {setting.name: setting.default for setting in SETTINGS}
    values.update(declared if declared is not None else read_config_files())
    if metadata is not None:
        values.update(from_frontmatter(metadata, document_dir))
    if overrides is not None:
        values.update(overrides)
    return _build(values)


def read_config(path: Path) -> dict[str, Any]:
    """Read one config file, refusing anything it should not contain."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or "it is not valid UTF-8 text"
        raise ConfigError(f"Could not read {path}: {detail.lower()}.") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}.") from exc

    values: dict[str, Any] = {}
    for key, value in data.items():
        setting = _BY_NAME.get(key)
        if setting is None:
            # Silently ignoring a misspelled key looks exactly like a setting
            # that does not work, which is a much worse afternoon than being
            # told which line is wrong. The theme loader refuses for the same
            # reason.
            raise ConfigError(
                f"{path}: unknown setting {key!r}.",
                hint=f"A config file takes: {', '.join(_BY_NAME)}.",
            )
        values[key] = _checked(setting, value, str(path), path.parent)
    return values


def from_frontmatter(
    metadata: Mapping[str, Any], document_dir: Path | None = None
) -> dict[str, Any]:
    """The conversion settings a document declares about itself.

    Only the keys that name a setting are read. Everything else in the
    frontmatter is the document's metadata, and an unknown key there is a
    title or a keyword list rather than a mistake.
    """
    values: dict[str, Any] = {}
    for key, value in metadata.items():
        setting = _BY_NAME.get(str(key).lower())
        if setting is not None and setting.frontmatter:
            values[setting.name] = _checked(setting, value, FRONTMATTER, document_dir)
    return values


def starter_config() -> str:
    """The commented file ``amethyst init`` writes.

    Generated from the settings rather than shipped as data, so that it cannot
    fall behind them: every key is here, with the default it actually has.
    """
    lines = [
        "# Amethyst settings for the documents in this directory.",
        "#",
        "# Every setting is listed with its default and commented out.",
        "# Uncomment the ones you want to change.",
        "#",
        "# A flag on the command line still wins over anything here, and so",
        "# does a value in a document's own frontmatter.",
    ]
    for setting in SETTINGS:
        value = setting.example if setting.default is None else _toml(setting.default)
        lines += ["", f"# {setting.help}", f"# {setting.name} = {value}"]
    return "\n".join([*lines, ""])


def _build(values: Mapping[str, Any]) -> Settings:
    """Turn merged values into the settings object the CLI reads."""
    return Settings(
        format=values["format"],
        theme=values["theme"],
        css=values["css"],
        toc=values["toc"],
        toc_depth=values["toc_depth"],
        title_page=values["title_page"],
        page_size=values["page_size"],
        margin=values["margin"],
        page_numbers=values["page_numbers"],
        highlight_style=values["highlight_style"],
        remote=values["remote"],
    )


def _checked(setting: Setting, value: Any, source: str, directory: Path | None) -> Any:
    """Validate one declared value, and locate it if it names a file."""
    if setting.kind is bool:
        if not isinstance(value, bool):
            raise _invalid(setting, value, source, "true or false")
    elif setting.kind is int:
        # A bool is an int as far as Python is concerned, and `toc_depth =
        # true` is not a depth.
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(setting, value, source, "a whole number")
        if setting.minimum is not None and value < setting.minimum:
            raise _invalid(setting, value, source, f"at least {setting.minimum}")
        if setting.maximum is not None and value > setting.maximum:
            raise _invalid(setting, value, source, f"at most {setting.maximum}")
    else:
        if not isinstance(value, str) or not value.strip():
            raise _invalid(setting, value, source, "text")
        value = value.strip()
        if setting.choices is not None and value not in setting.choices:
            raise _invalid(setting, value, source, f"one of {_or(setting.choices)}")
        names_a_file = setting.locate is not None and setting.locate(value)
        if names_a_file and directory is not None:
            value = _relative_to(value, directory)
    return value


def _relative_to(value: str, directory: Path) -> str:
    """Resolve a declared path against the file that declared it.

    A stylesheet named in ``~/.config/amethyst/config.toml`` means the one
    beside that file, not one that happens to share its name with something in
    whatever directory the command was run from.
    """
    candidate = Path(value)
    if candidate.is_absolute():
        return value
    return str((directory / candidate).resolve())


def _invalid(setting: Setting, value: Any, source: str, must: str) -> ConfigError:
    """The one shape a bad setting is reported in, wherever it was written."""
    return ConfigError(f"{source}: {setting.name} must be {must}, not {value!r}.")


def _or(choices: Sequence[str]) -> str:
    """Join choices the way a sentence would."""
    return " or ".join(
        [", ".join(choices[:-1]), choices[-1]] if len(choices) > 1 else choices
    )


def _toml(value: Any) -> str:
    """Write a default the way it would be written in the file."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _env(name: str) -> str | None:
    """One environment variable, treating an empty value as unset."""
    return os.environ.get(name) or None


__all__ = [
    "CONFIG_FILENAME",
    "SETTINGS",
    "Setting",
    "Settings",
    "config_files",
    "from_frontmatter",
    "read_config",
    "read_config_files",
    "resolve_settings",
    "starter_config",
    "user_config_path",
]
