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
from docx import Document as read_docx

from amethyst import cli
from amethyst.cli import (
    DASH,
    Format,
    main,
    resolve_format,
    resolve_output,
    resolve_theme,
)
from amethyst.config import CONFIG_FILENAME, user_config_path
from amethyst.errors import UsageError
from amethyst.render.furniture import CONTENTS_HEADING
from amethyst.theme import DEFAULT_THEME, builtin_names, load_theme

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


def test_themes_list_names_and_describes_the_builtins(monkeypatch, capsys):
    assert run(monkeypatch, "themes", "list") == 0
    out = capsys.readouterr().out
    for name in builtin_names():
        assert name in out
    assert load_theme(DEFAULT_THEME).description in out


def test_themes_show_prints_the_toml_it_would_be_copied_from(monkeypatch, capsys):
    assert run(monkeypatch, "themes", "show", DEFAULT_THEME) == 0
    out = capsys.readouterr().out
    assert "[fonts]" in out
    # Rich's markup is off for this: a hex colour is a style tag otherwise, and
    # the copy the user pastes back would be missing the value.
    assert "#6a3fa0" in out


def test_what_themes_show_prints_loads_back_as_a_theme(monkeypatch, capsys, tmp_path):
    """The command exists to be copied out of, so the copy has to work.

    At a narrow width too: Rich folds a long line to the terminal, and a fold
    inside a font stack would hand the user a file that no longer parses.
    """
    monkeypatch.setenv("COLUMNS", "40")
    assert run(monkeypatch, "themes", "show", DEFAULT_THEME) == 0

    copied = tmp_path / "copied.toml"
    copied.write_text(capsys.readouterr().out, encoding="utf-8")
    assert load_theme(str(copied)).fonts == load_theme(DEFAULT_THEME).fonts


def test_themes_show_refuses_a_theme_that_is_not_there(monkeypatch):
    assert run(monkeypatch, "themes", "show", "nope") == 2


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


def test_a_named_style_reaches_the_document(
    monkeypatch, doc, tmp_path, capsys, requires_weasyprint
):
    """Every flag the CLI accepts is honoured; none is merely tolerated."""
    out = tmp_path / "out.pdf"
    code = run(
        monkeypatch,
        "convert",
        str(doc),
        "-o",
        str(out),
        "--highlight-style",
        "monokai",
    )
    assert code == 0
    assert "not implemented" not in capsys.readouterr().err
    assert out.is_file()


def test_a_style_that_does_not_exist_is_bad_usage(monkeypatch, doc, capsys):
    code = run(
        monkeypatch, "convert", str(doc), "-f", "docx", "--highlight-style", "nope"
    )
    assert code == 2
    assert "Unknown highlighting style" in capsys.readouterr().err


# --- themes, once they are loaded -----------------------------------------


def test_a_theme_that_is_found_but_broken_is_a_conversion_failure(
    monkeypatch, doc, tmp_path, capsys
):
    """The other half of the split: not-there is usage, unreadable is not."""
    theme = tmp_path / "broken.toml"
    theme.write_text('[colors]\naccent = "not a colour"\n', encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc), "-f", "pdf", "-t", str(theme)) == 1
    assert "colors.accent" in capsys.readouterr().err


def test_a_theme_changes_the_document_it_renders(
    monkeypatch, doc, tmp_path, requires_weasyprint
):
    theme = tmp_path / "loud.toml"
    theme.write_text('[colors]\naccent = "#c00"\n', encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc), "-o", "out.pdf", "-t", str(theme)) == 0
    assert Path("out.pdf").read_bytes().startswith(b"%PDF-")


def test_page_geometry_flags_override_the_theme(
    monkeypatch, doc, capsys, requires_weasyprint
):
    code = run(
        monkeypatch,
        "convert",
        str(doc),
        "-o",
        "out.pdf",
        "--page-size",
        "Letter",
        "--margin",
        "3cm",
        "--verbose",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Letter" in out
    assert "3cm" in out


def test_page_geometry_falls_back_to_the_theme(
    monkeypatch, doc, capsys, requires_weasyprint
):
    assert run(monkeypatch, "convert", str(doc), "-o", "out.pdf", "--verbose") == 0
    out = capsys.readouterr().out
    theme = load_theme(DEFAULT_THEME)
    assert theme.page.size in out
    assert theme.page.margin in out


# --- document furniture ----------------------------------------------------


def test_the_contents_flags_are_reported_and_honoured(
    monkeypatch, doc, capsys, requires_weasyprint
):
    code = run(
        monkeypatch,
        "convert",
        str(doc),
        "-o",
        "out.pdf",
        "--toc",
        "--toc-depth",
        "2",
        "--title-page",
        "--verbose",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "depth 2" in out
    assert "title page" in out
    # Two pages of front matter in front of the one page the body fits on.
    assert "(3 pages)" in out


def test_a_contents_reaches_the_word_file_too(monkeypatch, doc, requires_weasyprint):
    assert run(monkeypatch, "convert", str(doc), "-o", "out.docx", "--toc") == 0
    document = read_docx("out.docx")
    assert document.paragraphs[0].text == CONTENTS_HEADING


def test_furniture_that_the_document_cannot_supply_warns_but_still_converts(
    monkeypatch, tmp_path, capsys, requires_weasyprint
):
    bare = tmp_path / "bare.md"
    bare.write_text("Just a paragraph.\n", encoding="utf-8")
    code = run(
        monkeypatch, "convert", str(bare), "-o", "out.pdf", "--toc", "--title-page"
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "--toc needs headings" in err
    assert "--title-page needs a title" in err


def test_a_toc_depth_past_the_last_heading_level_is_bad_usage(monkeypatch, doc):
    assert (
        run(monkeypatch, "convert", str(doc), "-o", "out.pdf", "--toc-depth", "7") == 2
    )


# --- config files ---------------------------------------------------------


def test_a_config_file_in_the_directory_changes_the_conversion(
    monkeypatch, doc, tmp_path, capsys
):
    (tmp_path / CONFIG_FILENAME).write_text('theme = "github"\n', encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc), "-f", "docx", "--verbose") == 0
    assert "github" in capsys.readouterr().out


def test_a_flag_beats_the_config_file(monkeypatch, doc, tmp_path, capsys):
    (tmp_path / CONFIG_FILENAME).write_text('theme = "github"\n', encoding="utf-8")
    code = run(
        monkeypatch, "convert", str(doc), "-f", "docx", "-t", "academic", "--verbose"
    )
    assert code == 0
    assert "academic" in capsys.readouterr().out


def test_a_flag_left_alone_does_not_overrule_the_config_file(
    monkeypatch, doc, tmp_path, capsys
):
    """The trap this whole mechanism exists to avoid: a default that wins."""
    (tmp_path / CONFIG_FILENAME).write_text("toc = true\ntoc_depth = 2\n", "utf-8")
    assert run(monkeypatch, "convert", str(doc), "-f", "docx", "--verbose") == 0
    assert "depth 2" in capsys.readouterr().out


def test_the_project_file_beats_the_user_file(
    monkeypatch, doc, tmp_path, capsys, config_home
):
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('theme = "github"\n', encoding="utf-8")
    (tmp_path / CONFIG_FILENAME).write_text('theme = "academic"\n', encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc), "-f", "docx", "--verbose") == 0
    assert "academic" in capsys.readouterr().out


def test_frontmatter_can_ask_for_a_contents(monkeypatch, tmp_path, capsys):
    source = tmp_path / "notes.md"
    source.write_text("---\ntitle: T\ntoc: true\n---\n\n# One\n\n## Two\n", "utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "docx", "--verbose") == 0
    out = capsys.readouterr().out
    assert "depth 3" in out


def test_a_config_file_can_choose_the_format(monkeypatch, doc, tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text('format = "docx"\n', encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc)) == 0
    assert doc.with_suffix(".docx").is_file()


def test_an_output_extension_beats_a_configured_format(monkeypatch, doc, tmp_path):
    """The config is the most general statement; -o is about this invocation."""
    (tmp_path / CONFIG_FILENAME).write_text('format = "pdf"\n', encoding="utf-8")
    out = tmp_path / "out.docx"
    assert run(monkeypatch, "convert", str(doc), "-o", str(out)) == 0
    assert out.is_file()
    assert read_docx(str(out)).paragraphs


def test_a_broken_config_file_is_a_conversion_failure_not_bad_usage(
    monkeypatch, doc, tmp_path, capsys
):
    (tmp_path / CONFIG_FILENAME).write_text("theme = [\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc), "-f", "docx") == 1
    assert "not valid TOML" in capsys.readouterr().err


def test_a_misspelled_setting_names_itself(monkeypatch, doc, tmp_path, capsys):
    (tmp_path / CONFIG_FILENAME).write_text("tocdepth = 2\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(doc), "-f", "docx") == 1
    assert "unknown setting 'tocdepth'" in capsys.readouterr().err


# --- init -----------------------------------------------------------------


def test_init_writes_a_config_file_that_reads_back(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, "init") == 0
    written = tmp_path / CONFIG_FILENAME
    assert written.is_file()
    assert "amethyst.toml" in capsys.readouterr().out
    # Every line is commented out, so writing it changes nothing.
    assert "theme" in written.read_text(encoding="utf-8")


def test_init_leaves_an_existing_file_alone(monkeypatch, tmp_path, capsys):
    existing = tmp_path / CONFIG_FILENAME
    existing.write_text('theme = "github"\n', encoding="utf-8")
    assert run(monkeypatch, "init") == 2
    assert existing.read_text(encoding="utf-8") == 'theme = "github"\n'
    assert "already exists" in capsys.readouterr().err


def test_a_file_written_by_init_is_read_by_convert(monkeypatch, doc, tmp_path, capsys):
    """The two commands have to agree about the file, or init is decoration."""
    assert run(monkeypatch, "init") == 0
    written = tmp_path / CONFIG_FILENAME
    written.write_text(
        written.read_text(encoding="utf-8").replace(
            '# theme = "default"', 'theme = "github"'
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert run(monkeypatch, "convert", str(doc), "-f", "docx", "--verbose") == 0
    assert "github" in capsys.readouterr().out


# --- remote images --------------------------------------------------------


def test_no_remote_leaves_a_linked_image_alone(monkeypatch, tmp_path, capsys):
    """The suite's offline fixture is the assertion: a fetch would raise."""
    source = tmp_path / "notes.md"
    source.write_text("![a](https://example.com/x.png)\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "docx", "--no-remote") == 0
    assert "not available locally" in capsys.readouterr().err


def test_remote_images_are_fetched_by_default(monkeypatch, tmp_path, fixtures):
    calls: list[str] = []
    png = (fixtures / "assets" / "amethyst.png").read_bytes()

    class Response(io.BytesIO):
        headers = {"Content-Type": "image/png"}

        def geturl(self) -> str:
            return "https://example.com/x.png"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def urlopen(request, timeout=None):
        calls.append(request.full_url)
        return Response(png)

    monkeypatch.setattr("amethyst.remote.urlopen", urlopen)
    source = tmp_path / "notes.md"
    source.write_text("![a](https://example.com/x.png)\n", encoding="utf-8")
    assert run(monkeypatch, "convert", str(source), "-f", "docx") == 0
    assert calls == ["https://example.com/x.png"]


# --- the last line before a traceback -------------------------------------


def test_an_unexpected_failure_is_a_line_and_not_a_traceback(monkeypatch, doc, capsys):
    """A traceback is for a maintainer; --verbose is how one asks for it."""

    def explode(*args: object, **kwargs: object):
        raise RuntimeError("the flux capacitor let go")

    monkeypatch.setattr(cli, "render_docx", explode)
    assert run(monkeypatch, "convert", str(doc), "-f", "docx") == 1
    captured = capsys.readouterr().err
    assert "RuntimeError: the flux capacitor let go" in captured
    assert "That is a bug in Amethyst" in captured
    assert "Traceback" not in captured


def test_a_usage_error_still_exits_two_and_not_one(monkeypatch, doc):
    """The catch-all must not swallow the errors that have their own codes."""
    assert run(monkeypatch, "convert", str(doc)) == 2
