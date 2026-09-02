"""The theme layer: what loads, what is refused, and what it compiles to.

Two things are worth stating about the shape of these tests. The default theme
is loaded rather than mocked, because it is also the schema every other theme
is validated and completed against — a test that invented its own defaults
would stop noticing when the shipped file and the code disagreed. And the CSS
is asserted as text, because text is what WeasyPrint is handed; the round trip
through a parser would only prove the parser works.
"""

from __future__ import annotations

import re

import pytest

from amethyst.errors import ThemeError, UsageError
from amethyst.theme import (
    DEFAULT_THEME,
    HEADING_LEVELS,
    Theme,
    base_css,
    builtin_names,
    default_theme,
    load_theme,
    locate_theme,
    read_theme_text,
)
from amethyst.theme.to_css import font_stack, number, page_css, root_css


@pytest.fixture
def write_theme(tmp_path):
    """Write a theme file and return its path as the CLI would spell it."""

    def _write(toml: str, name: str = "custom.toml") -> str:
        path = tmp_path / name
        path.write_text(toml, encoding="utf-8")
        return str(path)

    return _write


# --- the builtin default --------------------------------------------------


def test_the_default_theme_is_a_builtin_and_loads_complete():
    assert DEFAULT_THEME in builtin_names()
    theme = default_theme()
    assert theme.name == DEFAULT_THEME
    assert theme.description
    assert theme.fonts.body[-1] == "serif"
    assert theme.type.size > 0
    assert len(theme.type.headings) == HEADING_LEVELS
    assert theme.colors.text.startswith("#")
    assert theme.page.size == "A4"


def test_every_builtin_theme_loads():
    """The whole point of a builtin is that it cannot be the broken one."""
    for name in builtin_names():
        assert isinstance(load_theme(name), Theme)


def test_the_default_theme_is_read_once_and_shared():
    assert default_theme() is default_theme()


def test_a_theme_can_be_read_back_as_the_toml_it_was_written_as():
    text = read_theme_text(DEFAULT_THEME)
    assert "[fonts]" in text
    assert "[page]" in text


# --- locating -------------------------------------------------------------


def test_an_unknown_builtin_is_bad_usage_not_a_broken_theme():
    with pytest.raises(UsageError, match="Unknown theme"):
        locate_theme("nope")


def test_a_path_with_no_file_at_it_is_bad_usage(tmp_path):
    with pytest.raises(UsageError, match="No theme file"):
        locate_theme(str(tmp_path / "gone.toml"))


def test_a_theme_path_is_told_apart_from_a_builtin_name(write_theme):
    """A file called default.toml is that file, not the builtin of the name."""
    source = write_theme('[colors]\naccent = "#c00000"\n', name="default.toml")
    assert load_theme(source).colors.accent == "#c00000"
    assert default_theme().colors.accent != "#c00000"


# --- completing from the default ------------------------------------------


def test_a_theme_inherits_everything_it_does_not_declare(write_theme):
    theme = load_theme(write_theme('[colors]\naccent = "#c00000"\n'))
    default = default_theme()
    assert theme.colors.accent == "#c00000"
    assert theme.colors.text == default.colors.text
    assert theme.fonts.body == default.fonts.body
    assert theme.page == default.page


def test_a_theme_is_named_for_its_file_and_describes_only_itself(write_theme):
    theme = load_theme(write_theme("[type]\nsize = 12\n", name="report.toml"))
    assert theme.name == "report"
    # Not the default's description: a theme that says nothing about itself
    # should say nothing, rather than claim to be the theme it inherited from.
    assert theme.description == ""


def test_a_declared_description_survives(write_theme):
    theme = load_theme(write_theme('description = "Loud."\n[type]\nsize = 12\n'))
    assert theme.description == "Loud."


def test_an_empty_theme_is_the_default_under_another_name(write_theme):
    theme = load_theme(write_theme("\n"))
    assert theme.type == default_theme().type
    assert theme.colors == default_theme().colors


# --- refusing what will not work ------------------------------------------


def test_malformed_toml_is_a_theme_error(write_theme):
    with pytest.raises(ThemeError, match="not valid TOML"):
        load_theme(write_theme("[colors\n"))


def test_an_unknown_section_is_named_not_ignored(write_theme):
    with pytest.raises(ThemeError, match=r"unknown section \[colours\]"):
        load_theme(write_theme('[colours]\naccent = "#c00000"\n'))


def test_an_unknown_setting_is_named_not_ignored(write_theme):
    with pytest.raises(ThemeError, match="unknown setting 'accnet'"):
        load_theme(write_theme('[colors]\naccnet = "#c00000"\n'))


def test_a_section_that_is_not_a_table_is_refused(write_theme):
    with pytest.raises(ThemeError, match="must be a table"):
        load_theme(write_theme('colors = "purple"\n'))


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        ('[colors]\naccent = "purple"\n', "colors.accent"),
        ('[colors]\naccent = "#12345"\n', "colors.accent"),
        ("[type]\nsize = 0\n", "type.size"),
        ('[type]\nsize = "11pt"\n', "type.size"),
        ("[type]\nheading_weight = 1200\n", "type.heading_weight"),
        ("[type]\nheadings = [2, 1.5]\n", "type.headings"),
        ("[type]\nheadings = [2, 1.5, 1.2, 1.1, 1, 0]\n", "type.headings"),
        ("[spacing]\nblock = -1\n", "spacing.block"),
        ("[fonts]\nbody = []\n", "fonts.body"),
        ("[fonts]\nbody = [12]\n", "fonts.body"),
        ('[fonts]\nbody = ["Broken; }"]\n', "fonts.body"),
        ('[page]\nsize = ""\n', "page.size"),
        ('[page]\nmargin = "2cm; color: red"\n', "page.margin"),
        ("description = 4\n", "description"),
    ],
)
def test_a_value_that_cannot_work_is_refused_with_its_name(write_theme, toml, match):
    with pytest.raises(ThemeError, match=match):
        load_theme(write_theme(toml))


def test_a_boolean_is_not_accepted_as_a_number(write_theme):
    """``True`` is an ``int`` in Python, and would otherwise be a size of 1."""
    with pytest.raises(ThemeError, match="type.size"):
        load_theme(write_theme("[type]\nsize = true\n"))


# --- normalisation --------------------------------------------------------


def test_short_hex_colours_are_expanded(write_theme):
    """Word wants three bytes; CSS would have taken either."""
    theme = load_theme(write_theme('[colors]\naccent = "#C0F"\n'))
    assert theme.colors.accent == "#cc00ff"


def test_a_colour_is_lowercased_and_gets_its_hash(write_theme):
    assert load_theme(write_theme('[colors]\naccent = "6A3FA0"\n')).colors.accent == (
        "#6a3fa0"
    )


# --- page geometry --------------------------------------------------------


def test_page_geometry_can_be_overridden_one_side_at_a_time():
    theme = default_theme()
    assert theme.with_page(size="Letter").page.margin == theme.page.margin
    assert theme.with_page(margin="3cm").page.size == theme.page.size


def test_overriding_nothing_returns_the_theme_itself():
    theme = default_theme()
    assert theme.with_page() is theme


# --- compiling to CSS -----------------------------------------------------


def test_the_root_block_declares_what_the_stylesheet_reads():
    css = root_css(default_theme())
    # Every custom property base.css reads must be one the theme emits, or a
    # theme would silently leave part of the document unstyled.
    for name in sorted(set(_referenced_properties(base_css()))):
        assert f"--{name}:" in css, name


def test_the_root_block_is_only_custom_properties():
    """No rules here: how a document is laid out stays in one file."""
    css = root_css(default_theme())
    assert css.count("{") == 1
    for line in css.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("/*", ":root", "}")):
            assert stripped.startswith("--"), line


def test_sizes_are_emitted_with_units(write_theme):
    css = root_css(load_theme(write_theme("[type]\nsize = 12\nsmall = 9.5\n")))
    assert "--size-body: 12pt;" in css
    assert "--size-small: 9.5pt;" in css
    assert "--size-h1: 2em;" in css


def test_a_number_is_written_the_short_way():
    assert number(11) == "11"
    assert number(11.0) == "11"
    assert number(1.45) == "1.45"


def test_a_font_stack_quotes_only_the_names_that_need_it():
    stack = font_stack(["Iowan Old Style", "Palatino", "serif"])
    # The generic family must stay bare, or it becomes a search for a font
    # actually called "serif", which no machine has.
    assert stack == '"Iowan Old Style", Palatino, serif'


def test_the_page_block_carries_the_footer_styling_in_full():
    """A margin box inherits nothing from :root, so var() would resolve to gaps."""
    theme = default_theme()
    css = page_css(theme)
    assert "var(" not in css
    assert theme.colors.muted in css
    assert font_stack(theme.fonts.body) in css


def _referenced_properties(css: str) -> list[str]:
    """Every custom property a stylesheet reads through ``var()``."""
    return re.findall(r"var\(--([a-z0-9-]+)\)", css)
