"""YAML frontmatter: split it off the token stream, read it as metadata."""

from __future__ import annotations

from typing import Any

import yaml
from markdown_it.token import Token

from amethyst.errors import InputError


def split_frontmatter(tokens: list[Token]) -> tuple[dict[str, Any], list[Token]]:
    """Pull a leading ``front_matter`` token out and parse it as YAML.

    The parser is given the whole file, delimiters included, so every token's
    line map stays true to the source — a warning that names line 40 means line
    40 of the file the author actually wrote. The token is dropped here because
    nothing downstream should have to know it was ever in the stream.
    """
    if not tokens or tokens[0].type != "front_matter":
        return {}, tokens
    return parse_frontmatter(tokens[0].content), list(tokens[1:])


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the body of a frontmatter block into a metadata mapping.

    Keys are lowercased so that ``Title:`` and ``title:`` mean the same thing.
    Values are left exactly as YAML produced them — dates stay dates, lists
    stay lists — and are flattened to text only where they are displayed.
    """
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InputError(
            "The YAML frontmatter could not be parsed.", hint=_yaml_hint(exc)
        ) from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise InputError(
            f"The frontmatter is a {type(loaded).__name__}, "
            "not a set of key: value pairs.",
            hint="Frontmatter looks like `title: My Document`, one field per line.",
        )
    return {str(key).strip().lower(): value for key, value in loaded.items()}


def _yaml_hint(exc: yaml.YAMLError) -> str | None:
    """Turn PyYAML's mark into a line number the user can act on.

    The mark counts from the start of the frontmatter body, so add one for the
    opening ``---`` to get back to a line number in the file itself.
    """
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return str(problem) if problem else None
    where = f"line {mark.line + 2} of the file"
    return f"{problem} at {where}." if problem else f"Check {where}."
