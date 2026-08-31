"""The Typer application: argument parsing, resolution and exit codes.

Conversion is not wired up yet. Every command resolves its arguments for real
— format inference, output paths, theme names — and then prints the plan it
would have executed, so the surface can be exercised and tested before any
renderer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from amethyst import __version__
from amethyst.errors import AmethystError, UsageError

#: The conventional spelling of "stdin" or "stdout" as a path argument.
DASH = Path("-")

#: Known theme names. Replaced by a scan of ``theme/builtin`` once it exists.
BUILTIN_THEMES = ("default", "github", "academic")

#: The config file ``amethyst init`` writes into the working directory.
CONFIG_FILENAME = "amethyst.toml"

console = Console()
err_console = Console(stderr=True)


class Format(str, Enum):
    """Output formats. The value doubles as the output file extension."""

    pdf = "pdf"
    docx = "docx"


class PdfEngine(str, Enum):
    """PDF backends. One for now; the flag exists to keep the seam visible."""

    weasyprint = "weasyprint"


_FORMAT_BY_SUFFIX = {f".{fmt.value}": fmt for fmt in Format}


@dataclass
class State:
    """Cross-cutting flags that outlive argument parsing."""

    verbose: bool = False
    quiet: bool = False


state = State()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"amethyst {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="amethyst",
    help="Turn a Markdown file into a well-typeset PDF or Word document.",
    no_args_is_help=True,
    # Turns shell completion off entirely, not just the two --*-completion
    # flags: Typer registers its completion classes from the same code path
    # that builds those flags, so the _AMETHYST_COMPLETE env var stops working
    # too. Little is lost today — the completions worth having (theme names on
    # -t, Pygments styles on --highlight-style) are plain strings and would
    # need explicit shell_complete callbacks either way. Flip this back to True
    # when those exist.
    add_completion=False,
)
themes_app = typer.Typer(
    name="themes",
    help="Inspect the builtin themes.",
    no_args_is_help=True,
)
app.add_typer(themes_app)


@app.callback()
def cli(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Turn a Markdown file into a well-typeset PDF or Word document."""


def resolve_format(output: Path | None, fmt: Format | None) -> Format:
    """Decide the output format from the explicit flag or the output extension.

    An explicit ``-f`` always wins; a mismatch with the output extension is
    worth a warning but not an error, since the user said what they meant.
    """
    if fmt is not None:
        if output is not None and output != DASH:
            inferred = _FORMAT_BY_SUFFIX.get(output.suffix.lower())
            if inferred is not None and inferred is not fmt:
                warn(
                    f"--format {fmt.value} overrides the {output.suffix} "
                    f"extension of {output}."
                )
        return fmt

    if output is None:
        raise UsageError(
            "No output format given.",
            hint="Pass -f pdf or -f docx, or name the output with -o out.pdf.",
        )
    if output == DASH:
        raise UsageError(
            "Writing to stdout needs an explicit format.",
            hint="Pass -f pdf or -f docx.",
        )

    suffix = output.suffix.lower()
    inferred = _FORMAT_BY_SUFFIX.get(suffix)
    if inferred is None:
        described = (
            f"the extension {suffix!r}" if suffix else "a name with no extension"
        )
        raise UsageError(
            f"Cannot infer an output format from {described}.",
            hint="Use a .pdf or .docx output path, or pass -f explicitly.",
        )
    return inferred


def resolve_output(source: Path, output: Path | None, fmt: Format) -> Path | None:
    """Return where the document should be written, or ``None`` for stdout."""
    if output == DASH:
        return None
    if output is not None:
        return output
    if source == DASH:
        raise UsageError(
            "Reading from stdin needs an explicit output path.",
            hint="Pass -o out.pdf, or -o - to write the document to stdout.",
        )
    return source.with_suffix(f".{fmt.value}")


def resolve_theme(theme: str) -> str:
    """Validate a theme name, or accept a path to a theme file.

    Only existence is checked here, so the failures are ``UsageError``. Reading
    and validating the theme happens later and raises ``ThemeError`` — a theme
    that is present but broken is a different problem from one that was never
    named correctly.
    """
    candidate = Path(theme)
    if candidate.suffix.lower() == ".toml" or candidate.parent != Path("."):
        if not candidate.is_file():
            raise UsageError(f"No theme file at {theme}.")
        return str(candidate)
    if theme not in BUILTIN_THEMES:
        raise UsageError(
            f"Unknown theme {theme!r}.",
            hint=f"Builtin themes: {', '.join(BUILTIN_THEMES)}.",
        )
    return theme


def warn(message: str) -> None:
    """Report something the user should know about but that is not fatal."""
    if not state.quiet:
        err_console.print(f"[yellow]warning:[/] {escape(message)}")


def report(heading: str, rows: list[tuple[str, str]]) -> None:
    """Print a resolved plan — the stand-in for doing the work."""
    if state.quiet:
        return
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", justify="right", no_wrap=True)
    table.add_column(overflow="fold")
    for label, value in rows:
        table.add_row(label, escape(value))
    console.print(f"[bold]{heading}[/]")
    console.print(table)
    console.print("[dim]Not implemented yet.[/]")


@app.command()
def convert(
    source: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            exists=True,
            dir_okay=False,
            readable=True,
            allow_dash=True,
            help="Markdown file to convert, or - to read stdin.",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            dir_okay=False,
            allow_dash=True,
            help="Output file; the extension infers the format. - writes stdout.",
        ),
    ] = None,
    fmt: Annotated[
        Format | None,
        typer.Option(
            "-f",
            "--format",
            help="Output format. Required when --output is omitted or is stdout.",
        ),
    ] = None,
    theme: Annotated[
        str,
        typer.Option("-t", "--theme", help="Builtin theme name, or a path to a .toml."),
    ] = "default",
    css: Annotated[
        Path | None,
        typer.Option(
            "--css",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Extra CSS, appended last. PDF only.",
        ),
    ] = None,
    toc: Annotated[
        bool, typer.Option("--toc", help="Insert a table of contents.")
    ] = False,
    toc_depth: Annotated[
        int,
        typer.Option("--toc-depth", min=1, max=6, help="Heading levels in the TOC."),
    ] = 3,
    title: Annotated[
        str | None, typer.Option("--title", help="Override the frontmatter title.")
    ] = None,
    author: Annotated[
        str | None, typer.Option("--author", help="Override the frontmatter author.")
    ] = None,
    page_size: Annotated[
        str, typer.Option("--page-size", help="A4, Letter, or a custom size.")
    ] = "A4",
    margin: Annotated[
        str | None,
        typer.Option("--margin", help='CSS-style margin, e.g. "2cm" or "2cm 2.5cm".'),
    ] = None,
    no_page_numbers: Annotated[
        bool, typer.Option("--no-page-numbers", help="Suppress footer page numbers.")
    ] = False,
    highlight_style: Annotated[
        str, typer.Option("--highlight-style", help="Pygments style name.")
    ] = "default",
    pdf_engine: Annotated[
        PdfEngine, typer.Option("--pdf-engine", help="PDF backend.")
    ] = PdfEngine.weasyprint,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Print nothing but errors.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print detail, and tracebacks on error.")
    ] = False,
) -> None:
    """Convert a Markdown file to PDF or DOCX."""
    set_verbosity(quiet=quiet, verbose=verbose)

    resolved_format = resolve_format(output, fmt)
    destination = resolve_output(source, output, resolved_format)
    resolved_theme = resolve_theme(theme)

    if css is not None and resolved_format is not Format.pdf:
        warn("--css applies to PDF output only; ignoring it.")

    rows = [
        ("input", "stdin" if source == DASH else str(source)),
        ("output", "stdout" if destination is None else str(destination)),
        ("format", resolved_format.value),
        ("theme", resolved_theme),
    ]
    if css is not None and resolved_format is Format.pdf:
        rows.append(("extra css", str(css)))
    if title is not None:
        rows.append(("title", title))
    if author is not None:
        rows.append(("author", author))
    rows.append(("toc", f"depth {toc_depth}" if toc else "no"))
    rows.append(("page size", page_size))
    if margin is not None:
        rows.append(("margin", margin))
    rows.append(("page numbers", "no" if no_page_numbers else "yes"))
    rows.append(("highlighting", highlight_style))
    if resolved_format is Format.pdf:
        rows.append(("pdf engine", pdf_engine.value))

    report("Would convert:", rows)


@themes_app.command("list")
def themes_list() -> None:
    """List the builtin themes."""
    for name in BUILTIN_THEMES:
        console.print(name)


@themes_app.command("show")
def themes_show(
    name: Annotated[str, typer.Argument(metavar="NAME", help="Builtin theme name.")],
) -> None:
    """Print a theme's TOML, ready to copy and edit."""
    resolved = resolve_theme(name)
    report("Would print the TOML for:", [("theme", resolved)])


@app.command()
def init(
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Print nothing but errors.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print detail, and tracebacks on error.")
    ] = False,
) -> None:
    """Write a starter amethyst.toml into the current directory."""
    set_verbosity(quiet=quiet, verbose=verbose)

    destination = Path.cwd() / CONFIG_FILENAME
    if destination.exists():
        raise UsageError(
            f"{CONFIG_FILENAME} already exists here.",
            hint="Move or delete it first; Amethyst will not overwrite it.",
        )
    report("Would write:", [("config", str(destination))])


def set_verbosity(*, quiet: bool, verbose: bool) -> None:
    """Record the verbosity flags, which outlive the command that parsed them."""
    if quiet and verbose:
        raise UsageError("--quiet and --verbose contradict each other.")
    state.quiet = quiet
    state.verbose = verbose


def main() -> None:
    """Console-script entry point: run the app, and report errors as one line.

    Click handles its own usage errors (and already exits 2 for them). Anything
    raised as an ``AmethystError`` is ours, and gets a message plus its own exit
    code — with the traceback held back unless ``--verbose`` asked for it.
    """
    try:
        app()
    except AmethystError as exc:
        err_console.print(f"[bold red]error:[/] {escape(exc.message)}")
        if exc.hint:
            err_console.print(f"[dim]hint:[/] {escape(exc.hint)}")
        if state.verbose:
            err_console.print_exception()
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":
    main()
