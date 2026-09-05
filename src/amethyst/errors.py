"""The error hierarchy Amethyst reports with, rather than crashing.

Every error carries the process exit code it should produce, so the CLI can
turn it into one readable line instead of a traceback. The codes are the ones
the CLI contract promises: 0 ok, 1 conversion failure, 2 bad usage, 3 missing
system dependency.
"""

from __future__ import annotations


class AmethystError(Exception):
    """Base for anything the user should see as a message, not a traceback.

    ``hint`` is the actionable second line — the command to run, or the flag to
    pass. Leave it out when there is nothing concrete to suggest.
    """

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(AmethystError):
    """The invocation itself was wrong: conflicting flags, unusable paths."""

    exit_code = 2


class InputError(AmethystError):
    """The source document could not be read or parsed."""


class ConfigError(AmethystError):
    """A config file, or a document's frontmatter, said something unusable.

    A conversion failure rather than bad usage, for the same reason a broken
    theme is: the invocation was fine, and a file it read was not.
    """


class ThemeError(AmethystError):
    """A theme was located but could not be read or validated.

    A theme that simply is not there — an unknown builtin name, or a path with
    no file at it — is a ``UsageError`` instead. That is a mistyped invocation,
    not a broken document, and the two deserve different exit codes.
    """


class RenderError(AmethystError):
    """Conversion began but could not produce output."""


class MissingDependencyError(AmethystError):
    """A system library is absent, or present but not on the loader's path.

    The distinction matters enough to be worth spelling out in the message:
    telling someone to ``brew install pango`` when pango is already installed
    and merely unreachable sends them round in circles.
    """

    exit_code = 3
