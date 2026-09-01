"""The CLI surface: argument resolution, exit codes, and what gets reported.

Typer's ``CliRunner`` is deliberately not used for the exit-code tests. It
invokes the Typer app directly, which leaves ``main()`` — the wrapper that
turns an ``AmethystError`` into its own exit code — out of the call path, so
every one of our errors would come back as 1. Driving ``main()`` with a patched
argv tests the contract the shell actually sees.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from amethyst import cli
from amethyst.cli import (
    DASH,
    Format,
    main,
    resolve_format,
    resolve_output,
    resolve_theme,
)
from amethyst.errors import UsageError

DOC = """---
title: A Parsed Title
author: Ada Lovelace
---

# Heading

Body text.
"""


@pytest.fixture(autouse=True)
def isolated_cli(monkeypatch, tmp_path):
    """Reset the verbosity globals, and give Rich a width that never folds."""
    monkeypatch.setattr(cli, "state", cli.State())
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def doc(tmp_path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text(DOC, encoding="utf-8")
    return path


def run(monkeypatch, *argv: str, stdin: str | None = None) -> int:
    """Run the console-script entry point and return its real exit code."""
    monkeypatch.setattr(sys, "argv", ["amethyst", *argv])
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    with pytest.raises(SystemExit) as excinfo:
        main()
    return int(excinfo.value.code or 0)


# --- format resolution ----------------------------------------------------


def test_format_is_inferred_from_the_output_extension():
    assert resolve_format(Path("out.pdf"), None) is Format.pdf
    assert resolve_format(Path("out.DOCX"), None) is Format.docx


def test_an_explicit_format_beats_the_extension_but_says_so(capsys):
    assert resolve_format(Path("out.docx"), Format.pdf) is Format.pdf
    assert "overrides" in capsys.readouterr().err


def test_a_format_is_required_when_it_cannot_be_inferred():
    with pytest.raises(UsageError, match="No output format"):
        resolve_format(None, None)
    with pytest.raises(UsageError, match="stdout"):
        resolve_format(DASH, None)
    with pytest.raises(UsageError, match="Cannot infer"):
        resolve_format(Path("out.txt"), None)
    with pytest.raises(UsageError, match="Cannot infer"):
        resolve_format(Path("out"), None)


# --- output resolution ----------------------------------------------------


def test_output_defaults_to_the_input_with_the_extension_swapped():
    assert resolve_output(Path("a/notes.md"), None, Format.pdf) == Path("a/notes.pdf")
    assert resolve_output(Path("notes.md"), None, Format.docx) == Path("notes.docx")


def test_an_explicit_output_is_taken_as_given_and_a_dash_means_stdout():
    assert resolve_output(Path("notes.md"), Path("x/y.pdf"), Format.pdf) == Path(
        "x/y.pdf"
    )
    assert resolve_output(Path("notes.md"), DASH, Format.pdf) is None


def test_stdin_needs_an_explicit_output():
    with pytest.raises(UsageError, match="stdin"):
        resolve_output(DASH, None, Format.pdf)


# --- theme resolution -----------------------------------------------------


def test_builtin_theme_names_resolve_and_unknown_ones_do_not():
    assert resolve_theme("default") == "default"
    with pytest.raises(UsageError, match="Unknown theme"):
        resolve_theme("nope")


def test_a_theme_path_must_exist(tmp_path):
    theme = tmp_path / "custom.toml"
    with pytest.raises(UsageError, match="No theme file"):
        resolve_theme(str(theme))
    theme.write_text("[fonts]\n")
    assert resolve_theme(str(theme)) == str(theme)


# --- exit codes -----------------------------------------------------------


def test_version_and_help_succeed(monkeypatch, capsys):
    assert run(monkeypatch, "--version") == 0
    assert "amethyst" in capsys.readouterr().out


def test_a_convertible_document_exits_zero(monkeypatch, doc, requires_weasyprint):
    assert run(monkeypatch, "convert", str(doc), "-o", "out.pdf") == 0
    assert Path("out.pdf").read_bytes().startswith(b"%PDF-")


def test_bad_usage_exits_two(monkeypatch, doc, tmp_path):
    # No format and nothing to infer one from.
    assert run(monkeypatch, "convert", str(doc)) == 2
    # Unknown theme.
    assert run(monkeypatch, "convert", str(doc), "-f", "pdf", "-t", "nope") == 2
    # Contradictory verbosity.
    assert run(monkeypatch, "convert", str(doc), "-f", "pdf", "-q", "--verbose") == 2
    # A source file that is not there — Click rejects this one for us.
    assert run(monkeypatch, "convert", str(tmp_path / "gone.md"), "-f", "pdf") == 2


def test_init_refuses_to_overwrite_an_existing_config(monkeypatch, tmp_path):
    assert run(monkeypatch, "init") == 0
    (tmp_path / cli.CONFIG_FILENAME).write_text("[theme]\n")
    assert run(monkeypatch, "init") == 2


def test_themes_list_prints_the_builtins(monkeypatch, capsys):
    assert run(monkeypatch, "themes", "list") == 0
    assert capsys.readouterr().out.split() == list(cli.BUILTIN_THEMES)


# --- what convert reports -------------------------------------------------


def test_convert_reports_the_frontmatter_it_parsed(
    monkeypatch, doc, capsys, requires_weasyprint
):
    assert run(monkeypatch, "convert", str(doc), "-o", "out.pdf", "--verbose") == 0
    out = capsys.readouterr().out
    assert "A Parsed Title" in out
    assert "Ada Lovelace" in out
    assert "out.pdf" in out


def test_flags_override_the_frontmatter(monkeypatch, doc, capsys):
    assert (
        run(
            monkeypatch,
            "convert",
            str(doc),
            "-f",
            "docx",
            "--verbose",
            "--title",
            "Flag Title",
            "--author",
            "Grace Hopper",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Flag Title" in out
    assert "Grace Hopper" in out
    assert "A Parsed Title" not in out
    assert "notes.docx" in out  # the output path, inferred from the format


def test_an_untitled_document_is_reported_as_such(
    monkeypatch, tmp_path, capsys, requires_weasyprint
):
    source = tmp_path / "bare.md"
    source.write_text("Just a paragraph.\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "pdf", "--verbose") == 0
    assert "(untitled)" in capsys.readouterr().out


def test_a_missing_image_warns_but_still_exits_zero(
    monkeypatch, tmp_path, capsys, requires_weasyprint
):
    source = tmp_path / "notes.md"
    source.write_text("# T\n\n![pic](gone.png)\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "pdf") == 0
    err = capsys.readouterr().err
    assert "image not found" in err
    assert "gone.png" in err
    assert "line 3" in err


def test_quiet_suppresses_the_report_and_the_warnings(
    monkeypatch, tmp_path, capsys, requires_weasyprint
):
    source = tmp_path / "notes.md"
    source.write_text("# T\n\n![pic](gone.png)\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "pdf", "--quiet") == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_css_is_ignored_for_docx_with_a_warning(monkeypatch, doc, tmp_path, capsys):
    css = tmp_path / "extra.css"
    css.write_text("p { color: red }\n")
    assert run(monkeypatch, "convert", str(doc), "-f", "docx", "--css", str(css)) == 0
    assert "--css applies to PDF output only" in capsys.readouterr().err


def test_a_document_can_be_read_from_stdin(monkeypatch, capsys, requires_weasyprint):
    code = run(
        monkeypatch,
        "convert",
        "-",
        "-o",
        "out.pdf",
        "--verbose",
        stdin="# Piped In\n\nBody.\n",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "stdin" in out
    assert "Piped In" in out


def test_a_broken_document_is_one_line_not_a_traceback(monkeypatch, tmp_path, capsys):
    source = tmp_path / "bad.md"
    source.write_text("---\ntitle: [unclosed\n---\n\nBody\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "pdf") == 1
    err = capsys.readouterr().err
    assert "frontmatter could not be parsed" in err
    assert "Traceback" not in err


# --- writing the document -------------------------------------------------


def test_a_pdf_can_be_written_to_stdout(
    monkeypatch, doc, capsysbinary, requires_weasyprint
):
    assert run(monkeypatch, "convert", str(doc), "-f", "pdf", "-o", "-") == 0
    captured = capsysbinary.readouterr()
    assert captured.out.startswith(b"%PDF-")
    assert captured.out.rstrip().endswith(b"%%EOF")


def test_nothing_but_the_document_reaches_stdout(
    monkeypatch, doc, capsysbinary, requires_weasyprint
):
    """The whole reason out_console() exists: commentary must not land in the file."""
    assert (
        run(monkeypatch, "convert", str(doc), "-f", "pdf", "-o", "-", "--verbose") == 0
    )
    captured = capsysbinary.readouterr()
    assert b"Converting" not in captured.out
    assert b"wrote" not in captured.out
    assert b"Converting" in captured.err
    assert b"wrote stdout" in captured.err


def test_an_unwritable_output_is_one_line_not_a_traceback(
    monkeypatch, doc, tmp_path, capsys, requires_weasyprint
):
    destination = tmp_path / "no-such-directory" / "out.pdf"
    assert run(monkeypatch, "convert", str(doc), "-o", str(destination)) == 1
    err = capsys.readouterr().err
    assert "Could not write" in err
    assert "Traceback" not in err


def test_a_successful_conversion_says_what_it_wrote(
    monkeypatch, doc, capsys, requires_weasyprint
):
    assert run(monkeypatch, "convert", str(doc), "-o", "out.pdf") == 0
    assert "wrote out.pdf (1 page)" in capsys.readouterr().out


# --- flags that are accepted but not honoured yet --------------------------


def test_an_unbuilt_flag_says_so_rather_than_being_ignored(
    monkeypatch, doc, capsys, requires_weasyprint
):
    code = run(
        monkeypatch,
        "convert",
        str(doc),
        "-o",
        "out.pdf",
        "-t",
        "github",
        "--toc",
        "--highlight-style",
        "monokai",
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "themes are not implemented yet" in err
    assert "--toc is not implemented yet" in err
    assert "--highlight-style is not implemented yet" in err


def test_the_default_theme_and_style_pass_without_comment(
    monkeypatch, doc, capsys, requires_weasyprint
):
    assert run(monkeypatch, "convert", str(doc), "-o", "out.pdf") == 0
    assert "not implemented yet" not in capsys.readouterr().err
