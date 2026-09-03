"""The Typer application: argument parsing, resolution and exit codes.

Both formats convert for real here. The one thing worth knowing about this
module is that the document and the commentary can both end up on stdout:
``-o -`` writes the document there, and a progress line printed alongside it
would land inside the file. So every human-readable line goes through
``out_console()``, which steps aside to stderr when stdout belongs to the
document.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from amethyst import __version__
from amethyst.document import Document, load_document
from amethyst.errors import AmethystError, RenderError, UsageError
from amethyst.parse import AssetKind
from amethyst.render import RenderOptions, render_docx, render_pdf
from amethyst.theme import (
    DEFAULT_THEME,
    builtin_names,
    load_theme,
    locate_theme,
    read_theme_text,
)

#: The conventional spelling of "stdin" or "stdout" as a path argument.
DASH = Path("-")

#: The highlighting style used when the user names none. Held as a constant
#: because the flag needs it twice: once as the default, and once to notice
#: that the user asked for something other than it.
DEFAULT_HIGHLIGHT_STYLE = "default"

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
    #: True once the converted document is going to stdout, which makes stdout
    #: unavailable for anything a human is meant to read.
    document_on_stdout: bool = False


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
    named correctly, and the two exit differently.
    """
    return locate_theme(theme)


def apply_overrides(
    document: Document, *, title: str | None, author: str | None
) -> None:
    """Let --title and --author win over the frontmatter that declared them."""
    if title is not None:
        document.metadata["title"] = title
    if author is not None:
        document.metadata["author"] = author


def warn_about_missing_assets(document: Document) -> None:
    """Warn once per reference that points at a file which is not there.

    A missing image is not fatal — the document still converts, with a gap
    where the picture was — so this warns and continues rather than raising.
    """
    for asset in document.missing_assets:
        noun = "image" if asset.kind is AssetKind.image else "linked file"
        where = f" (line {asset.line})" if asset.line is not None else ""
        warn(f"{noun} not found: {asset.reference}{where}")


def warn(message: str) -> None:
    """Report something the user should know about but that is not fatal."""
    if not state.quiet:
        err_console.print(f"[yellow]warning:[/] {escape(message)}")


def out_console() -> Console:
    """Where a line meant for a human goes.

    Normally stdout. When the converted document is being written to stdout,
    anything else printed there would end up inside the file, so it steps
    aside to stderr — which is also where a shell pipeline expects commentary.
    """
    return err_console if state.document_on_stdout else console


def report(heading: str, rows: list[tuple[str, str]]) -> None:
    """Print a labelled table of the values a command resolved."""
    if state.quiet:
        return
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", justify="right", no_wrap=True)
    table.add_column(overflow="fold")
    for label, value in rows:
        table.add_row(label, escape(value))
    destination = out_console()
    destination.print(f"[bold]{heading}[/]")
    destination.print(table)


def report_unbuilt(heading: str, rows: list[tuple[str, str]]) -> None:
    """Print what a command would have done, for the parts not built yet."""
    if state.quiet:
        return
    report(heading, rows)
    out_console().print("[dim]Not implemented yet.[/]")


def report_written(destination: Path | None, pages: int | None) -> None:
    """Confirm the conversion, and say enough to show it produced a document."""
    if state.quiet:
        return
    where = "stdout" if destination is None else str(destination)
    detail = "" if pages is None else f" ({pages} page{'' if pages == 1 else 's'})"
    out_console().print(f"wrote {escape(where)}{detail}")


def warn_about_unbuilt_flags(*, toc: bool, highlight_style: str) -> None:
    """Say so when a flag was accepted but cannot be honoured yet.

    These disappear as the features behind them land. Until then, quietly
    ignoring a flag the user went out of their way to pass is the worse
    failure: the output looks wrong and nothing explains why.
    """
    if toc:
        warn("--toc is not implemented yet; the document will have no contents.")
    if highlight_style != DEFAULT_HIGHLIGHT_STYLE:
        warn("--highlight-style is not implemented yet; code is not highlighted.")


def write_document(data: bytes, destination: Path | None) -> None:
    """Write the finished document out, to a file or to stdout."""
    if destination is None:
        _write_stdout(data)
        return
    try:
        destination.write_bytes(data)
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise RenderError(f"Could not write {destination}: {detail.lower()}.") from exc


def _write_stdout(data: bytes) -> None:
    """Write the document's bytes to stdout, without touching the encoding."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        raise RenderError(
            "stdout cannot take the raw bytes of a document.",
            hint="Write to a file with -o instead.",
        )
    buffer.write(data)
    buffer.flush()


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
    ] = DEFAULT_THEME,
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
        str | None,
        typer.Option(
            "--page-size",
            show_default="the theme's",
            help="A4, Letter, or a custom size.",
        ),
    ] = None,
    margin: Annotated[
        str | None,
        typer.Option(
            "--margin",
            show_default="the theme's",
            help='CSS-style margin, e.g. "2cm" or "2cm 2.5cm".',
        ),
    ] = None,
    no_page_numbers: Annotated[
        bool, typer.Option("--no-page-numbers", help="Suppress footer page numbers.")
    ] = False,
    highlight_style: Annotated[
        str, typer.Option("--highlight-style", help="Pygments style name.")
    ] = DEFAULT_HIGHLIGHT_STYLE,
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
    # Settled before anything is printed, because it decides where printing
    # goes: a PDF on stdout leaves no room for a progress line beside it.
    state.document_on_stdout = destination is None
    resolved_theme = resolve_theme(theme)

    if css is not None and resolved_format is not Format.pdf:
        warn("--css applies to PDF output only; ignoring it.")
    warn_about_unbuilt_flags(toc=toc, highlight_style=highlight_style)

    # A flag that names page geometry overrides the theme that declares it,
    # which leaves the theme as the one thing a renderer has to be handed.
    loaded_theme = load_theme(resolved_theme).with_page(size=page_size, margin=margin)

    document = load_document(None if source == DASH else source)
    apply_overrides(document, title=title, author=author)
    warn_about_missing_assets(document)

    rows = [
        ("input", "stdin" if source == DASH else str(source)),
        ("output", "stdout" if destination is None else str(destination)),
        ("format", resolved_format.value),
        ("theme", resolved_theme),
    ]
    if css is not None and resolved_format is Format.pdf:
        rows.append(("extra css", str(css)))
    rows.append(("title", document.title or "(untitled)"))
    if document.author is not None:
        rows.append(("author", document.author))
    rows.append(("toc", f"depth {toc_depth}" if toc else "no"))
    rows.append(("page size", loaded_theme.page.size))
    rows.append(("margin", loaded_theme.page.margin))
    rows.append(("page numbers", "no" if no_page_numbers else "yes"))
    rows.append(("highlighting", highlight_style))
    if resolved_format is Format.pdf:
        rows.append(("pdf engine", pdf_engine.value))

    if state.verbose:
        report("Converting:", rows)

    render = render_pdf if resolved_format is Format.pdf else render_docx
    result = render(
        document,
        RenderOptions(
            theme=loaded_theme,
            extra_css=css,
            page_numbers=not no_page_numbers,
            warn=warn,
        ),
    )
    write_document(result.data, destination)
    report_written(destination, result.pages)


@themes_app.command("list")
def themes_list() -> None:
    """List the builtin themes."""
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(overflow="fold")
    for name in builtin_names():
        table.add_row(name, escape(load_theme(name).description))
    console.print(table)


@themes_app.command("show")
def themes_show(
    name: Annotated[str, typer.Argument(metavar="NAME", help="Builtin theme name.")],
) -> None:
    """Print a theme's TOML, ready to copy and edit."""
    # Printed raw: this is a file meant to be copied back out, so Rich must not
    # touch it. Markup off, because a colour written as [#6a3fa0] is a style tag
    # to Rich and a value to everyone else; soft wrapping on, because folding a
    # long line at the terminal width would put a newline inside the TOML.
    console.print(
        read_theme_text(resolve_theme(name)),
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


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
    report_unbuilt("Would write:", [("config", str(destination))])


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
