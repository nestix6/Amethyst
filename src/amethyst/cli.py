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
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from amethyst import __version__
from amethyst.config import (
    CONFIG_FILENAME,
    SETTINGS,
    config_files,
    read_config_files,
    resolve_settings,
    starter_config,
)
from amethyst.document import Document, load_document
from amethyst.errors import AmethystError, RenderError, UsageError
from amethyst.parse import AssetKind
from amethyst.remote import fetch_remote_images
from amethyst.render import (
    DEFAULT_HIGHLIGHT_STYLE,
    RenderOptions,
    render_docx,
    render_pdf,
    resolve_highlight_style,
)
from amethyst.render.furniture import MAX_TOC_DEPTH
from amethyst.theme import (
    DEFAULT_THEME,
    builtin_names,
    load_theme,
    locate_theme,
    read_theme_text,
)

#: The conventional spelling of "stdin" or "stdout" as a path argument.
DASH = Path("-")

#: The flags that state a setting *negatively*: ``--no-page-numbers`` sets
#: ``page_numbers`` to false. A flag reads better as the thing you turn off and
#: a setting reads better as the thing you turn on, so the two disagree, and
#: this is the one place that has to know it.
NEGATED_FLAGS = {"no_page_numbers": "page_numbers", "no_remote": "remote"}

#: The flags whose parameter is simply spelled differently from its setting —
#: ``fmt`` because ``format`` is a builtin. Everything not named here or above
#: carries the setting of the same name.
FLAG_SETTINGS = {"fmt": "format"}

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

#: The settings a flag is allowed to override, which is every setting there is.
_SETTING_NAMES = frozenset(setting.name for setting in SETTINGS)


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
    """Print the version and stop, before any argument is validated."""
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


def resolve_format(
    output: Path | None, fmt: Format | None, configured: Format | None = None
) -> Format:
    """Decide the output format, from the flag, the output name or a config file.

    In that order, which is the order of how specific each one is to this
    invocation. An explicit ``-f`` always wins; a mismatch with the output
    extension is worth a warning but not an error, since the user said what
    they meant. A configured format is the most general statement there is, so
    an output path that names an extension outranks it.
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

    if output is not None and output != DASH:
        suffix = output.suffix.lower()
        inferred = _FORMAT_BY_SUFFIX.get(suffix)
        if inferred is not None:
            return inferred
        if configured is not None:
            return configured
        described = (
            f"the extension {suffix!r}" if suffix else "a name with no extension"
        )
        raise UsageError(
            f"Cannot infer an output format from {described}.",
            hint="Use a .pdf or .docx output path, or pass -f explicitly.",
        )

    if configured is not None:
        return configured
    if output == DASH:
        raise UsageError(
            "Writing to stdout needs an explicit format.",
            hint="Pass -f pdf or -f docx.",
        )
    raise UsageError(
        "No output format given.",
        hint="Pass -f pdf or -f docx, or name the output with -o out.pdf.",
    )


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


def report_written(destination: Path | None, pages: int | None) -> None:
    """Confirm the conversion, and say enough to show it produced a document."""
    if state.quiet:
        return
    where = "stdout" if destination is None else str(destination)
    detail = "" if pages is None else f" ({pages} page{'' if pages == 1 else 's'})"
    out_console().print(f"wrote {escape(where)}{detail}")


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
    ctx: typer.Context,
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
        typer.Option(
            "--toc-depth",
            min=1,
            max=MAX_TOC_DEPTH,
            help="Heading levels in the TOC.",
        ),
    ] = 3,
    title_page: Annotated[
        bool,
        typer.Option("--title-page", help="Open with a title page from frontmatter."),
    ] = False,
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
    no_remote: Annotated[
        bool,
        typer.Option("--no-remote", help="Do not download images from the network."),
    ] = False,
    highlight_style: Annotated[
        str,
        typer.Option(
            "--highlight-style", help="Pygments style name, or none for no colour."
        ),
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

    # Read once, merged twice: the format has to be settled before the document
    # is opened, and everything else after, once its frontmatter is in hand.
    files = config_files()
    declared = read_config_files(files)
    overrides = passed_settings(ctx)
    early = resolve_settings(declared=declared, overrides=overrides)

    resolved_format = resolve_format(output, fmt, _format(early.format))
    destination = resolve_output(source, output, resolved_format)
    # Settled before anything is printed, because it decides where printing
    # goes: a PDF on stdout leaves no room for a progress line beside it.
    state.document_on_stdout = destination is None

    document = load_document(None if source == DASH else source)
    apply_overrides(document, title=title, author=author)
    settings = resolve_settings(
        declared=declared,
        metadata=document.metadata,
        document_dir=document.base_dir,
        overrides=overrides,
    )

    resolved_theme = resolve_theme(settings.theme)
    resolved_highlighting = resolve_highlight_style(settings.highlight_style)
    extra_css = Path(settings.css) if settings.css is not None else None
    if extra_css is not None and resolved_format is not Format.pdf:
        # Only worth saying when this invocation asked for it. A config file
        # that names a stylesheet for a directory of documents is not making a
        # mistake every time one of them is converted to Word.
        if "css" in overrides:
            warn("--css applies to PDF output only; ignoring it.")
        extra_css = None

    # A flag that names page geometry overrides the theme that declares it,
    # which leaves the theme as the one thing a renderer has to be handed.
    loaded_theme = load_theme(resolved_theme).with_page(
        size=settings.page_size, margin=settings.margin
    )

    rows = [
        ("input", "stdin" if source == DASH else str(source)),
        ("output", "stdout" if destination is None else str(destination)),
        ("format", resolved_format.value),
        ("theme", resolved_theme),
    ]
    if files:
        rows.append(("config", ", ".join(str(path) for path in files)))
    if extra_css is not None:
        rows.append(("extra css", str(extra_css)))
    rows.append(("title", document.title or "(untitled)"))
    if document.author is not None:
        rows.append(("author", document.author))
    rows.append(("toc", f"depth {settings.toc_depth}" if settings.toc else "no"))
    rows.append(("title page", "yes" if settings.title_page else "no"))
    rows.append(("page size", loaded_theme.page.size))
    rows.append(("margin", loaded_theme.page.margin))
    rows.append(("page numbers", "yes" if settings.page_numbers else "no"))
    rows.append(("highlighting", resolved_highlighting))
    rows.append(("remote images", "yes" if settings.remote else "no"))
    if resolved_format is Format.pdf:
        rows.append(("pdf engine", pdf_engine.value))

    if state.verbose:
        report("Converting:", rows)

    # After the plan is printed: this is the one step that can take a visible
    # amount of time, and a user watching it wait deserves to already know
    # what it is doing.
    fetch_remote_images(document, enabled=settings.remote, warn=warn)
    warn_about_missing_assets(document)

    render = render_pdf if resolved_format is Format.pdf else render_docx
    result = render(
        document,
        RenderOptions(
            theme=loaded_theme,
            extra_css=extra_css,
            page_numbers=settings.page_numbers,
            toc=settings.toc,
            toc_depth=settings.toc_depth,
            title_page=settings.title_page,
            highlight_style=resolved_highlighting,
            warn=warn,
        ),
    )
    write_document(result.data, destination)
    report_written(destination, result.pages)


def passed_settings(ctx: typer.Context) -> dict[str, Any]:
    """The settings the command line actually stated, and only those.

    A flag left alone must not overrule a config file with the default it was
    going to have anyway, so what matters is not a parameter's value but
    whether it was typed. Click records that per parameter, which is the one
    reliable way to ask: comparing against the default cannot tell
    ``--toc-depth 3`` from not passing it.
    """
    given: dict[str, Any] = {}
    for name, value in ctx.params.items():
        setting = NEGATED_FLAGS.get(name) or FLAG_SETTINGS.get(name, name)
        if setting not in _SETTING_NAMES or not _was_typed(ctx, name):
            continue
        if name in NEGATED_FLAGS:
            given[setting] = not value
        elif isinstance(value, Enum):
            given[setting] = value.value
        elif isinstance(value, Path):
            given[setting] = str(value)
        else:
            given[setting] = value
    return given


def _was_typed(ctx: typer.Context, name: str) -> bool:
    """Whether a parameter's value came from the command line.

    Compared by name rather than against the ``ParameterSource`` enum itself:
    Typer vendors its own copy of Click in recent versions, so the enum has no
    stable import path, and the member's name does.
    """
    source = ctx.get_parameter_source(name)
    return source is not None and source.name != "DEFAULT"


def _format(name: str | None) -> Format | None:
    """A configured format name as the enum. Validated when it was read."""
    return None if name is None else Format(name)


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
    try:
        destination.write_text(starter_config(), encoding="utf-8")
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise RenderError(f"Could not write {destination}: {detail.lower()}.") from exc
    report_written(destination, None)


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

    Anything else is a bug, and says so. A traceback is the right thing to hand
    a maintainer and the wrong thing to hand someone who typed a command, so it
    is held behind ``--verbose`` along with the rest of them. ``SystemExit`` and
    ``KeyboardInterrupt`` are not ``Exception`` and so pass through untouched,
    which is what leaves Click's own exits and a ctrl-C alone.
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
    except Exception as exc:  # noqa: BLE001 - the last line before a traceback
        err_console.print(
            f"[bold red]error:[/] {escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        err_console.print(
            "[dim]hint:[/] That is a bug in Amethyst, not something you did. "
            "Run it again with --verbose for the traceback."
        )
        if state.verbose:
            err_console.print_exception()
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
