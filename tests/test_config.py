"""Config files and frontmatter: what they may say, and who wins.

The order under test is the one the module documents — defaults, then the
user's file, then the project's, then the document's frontmatter, then the
flags. Each of those overriding the last is the whole feature; a test that only
proved a file could be read would prove nothing about the part that is easy to
get wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from amethyst.config import (
    CONFIG_FILENAME,
    SETTINGS,
    config_files,
    from_frontmatter,
    read_config,
    read_config_files,
    resolve_settings,
    starter_config,
    user_config_path,
)
from amethyst.errors import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 only
    import tomli as tomllib


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- the defaults ---------------------------------------------------------


def test_settings_with_nothing_declared_are_the_defaults():
    settings = resolve_settings(declared={})
    assert settings.theme == "default"
    assert settings.toc is False
    assert settings.toc_depth == 3
    assert settings.page_numbers is True
    assert settings.remote is True
    assert settings.format is None


def test_every_setting_has_something_to_write_in_a_starter_file():
    """A default of "say nothing" still needs an example, or init writes None."""
    for setting in SETTINGS:
        assert setting.default is not None or setting.example is not None


# --- reading a file -------------------------------------------------------


def test_a_config_file_overrides_the_defaults(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, 'theme = "github"\ntoc = true\n')
    settings = resolve_settings(declared=read_config_files([path]))
    assert settings.theme == "github"
    assert settings.toc is True
    # Untouched settings keep their defaults rather than being cleared.
    assert settings.toc_depth == 3


def test_the_project_file_is_read_after_the_user_file(tmp_path):
    user = write(tmp_path / "user.toml", 'theme = "github"\ntoc = true\n')
    project = write(tmp_path / CONFIG_FILENAME, 'theme = "academic"\n')
    settings = resolve_settings(declared=read_config_files([user, project]))
    assert settings.theme == "academic"
    # The user's file still speaks for anything the project's does not.
    assert settings.toc is True


def test_config_files_lists_the_user_file_then_the_project_one(
    tmp_path, config_home, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    write(user_config_path(), "toc = true\n")
    write(tmp_path / CONFIG_FILENAME, "toc = false\n")
    assert config_files() == [user_config_path(), tmp_path / CONFIG_FILENAME]


def test_a_config_file_that_is_not_there_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config_files() == []
    assert read_config_files() == {}


# --- refusing what it should ----------------------------------------------


def test_an_unknown_setting_is_refused_rather_than_ignored(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, 'them = "github"\n')
    with pytest.raises(ConfigError) as excinfo:
        read_config(path)
    assert "unknown setting 'them'" in excinfo.value.message
    assert "theme" in (excinfo.value.hint or "")


def test_a_setting_of_the_wrong_type_is_refused(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, "toc = 1\n")
    with pytest.raises(ConfigError, match="must be true or false"):
        read_config(path)


def test_a_depth_is_a_number_and_not_a_flag(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, "toc_depth = true\n")
    with pytest.raises(ConfigError, match="must be a whole number"):
        read_config(path)


def test_a_depth_outside_the_heading_levels_is_refused(tmp_path):
    too_small = ("toc_depth = 0", "at least 1")
    too_large = ("toc_depth = 9", "at most 6")
    for text, complaint in (too_small, too_large):
        path = write(tmp_path / CONFIG_FILENAME, f"{text}\n")
        with pytest.raises(ConfigError, match=complaint):
            read_config(path)


def test_a_format_that_is_neither_is_refused(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, 'format = "epub"\n')
    with pytest.raises(ConfigError, match="pdf or docx"):
        read_config(path)


def test_a_file_that_is_not_toml_says_so(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, "theme = [\n")
    with pytest.raises(ConfigError, match="not valid TOML"):
        read_config(path)


# --- paths resolve against whatever declared them -------------------------


def test_a_relative_path_resolves_against_the_file_that_declared_it(tmp_path):
    directory = tmp_path / "elsewhere"
    path = write(directory / CONFIG_FILENAME, 'theme = "themes/mine.toml"\n')
    values = read_config(path)
    assert values["theme"] == str((directory / "themes" / "mine.toml").resolve())


def test_a_builtin_theme_name_is_left_alone(tmp_path):
    path = write(tmp_path / CONFIG_FILENAME, 'theme = "github"\n')
    assert read_config(path)["theme"] == "github"


def test_a_bare_stylesheet_name_resolves_beside_the_config_file(tmp_path):
    """Unlike a theme, a css value is always a file — there are no builtins."""
    directory = tmp_path / "elsewhere"
    path = write(directory / CONFIG_FILENAME, 'css = "house.css"\n')
    assert read_config(path)["css"] == str((directory / "house.css").resolve())


def test_an_absolute_path_is_left_alone(tmp_path):
    absolute = tmp_path / "mine.toml"
    path = write(tmp_path / CONFIG_FILENAME, f'theme = "{absolute}"\n')
    assert read_config(path)["theme"] == str(absolute)


# --- frontmatter ----------------------------------------------------------


def test_frontmatter_contributes_the_settings_it_names():
    values = from_frontmatter({"title": "A Paper", "toc": True, "theme": "academic"})
    assert values == {"toc": True, "theme": "academic"}


def test_frontmatter_leaves_metadata_alone():
    """Everything in a document that is not a setting is its metadata."""
    metadata = {"title": "x", "keywords": ["a", "b"], "date": "2026-01-01"}
    assert from_frontmatter(metadata) == {}


def test_frontmatter_cannot_choose_the_output_format():
    """Where the file goes is the invocation's business, not the document's."""
    assert from_frontmatter({"format": "docx"}) == {}


def test_frontmatter_beats_a_config_file():
    settings = resolve_settings(declared={"toc": False}, metadata={"toc": True})
    assert settings.toc is True


def test_a_flag_beats_frontmatter():
    settings = resolve_settings(
        declared={"toc": False}, metadata={"toc": True}, overrides={"toc": False}
    )
    assert settings.toc is False


def test_a_bad_value_in_frontmatter_names_the_document():
    with pytest.raises(ConfigError, match="frontmatter"):
        from_frontmatter({"toc_depth": "deep"})


# --- the starter file -----------------------------------------------------


def test_the_starter_file_is_valid_toml_and_says_nothing():
    """Every line is commented out, so writing one changes no conversion."""
    assert tomllib.loads(starter_config()) == {}


def test_the_starter_file_lists_every_setting_and_only_settings(tmp_path):
    uncommented = "\n".join(
        line.removeprefix("# ")
        for line in starter_config().splitlines()
        if " = " in line
    )
    path = write(tmp_path / CONFIG_FILENAME, uncommented + "\n")
    values = read_config(path)
    assert set(values) == {setting.name for setting in SETTINGS}


def test_the_starter_file_writes_the_defaults_it_claims_to(tmp_path):
    """The file is generated from the settings, so it cannot drift from them."""
    uncommented = "\n".join(
        line.removeprefix("# ")
        for line in starter_config().splitlines()
        if " = " in line
    )
    path = write(tmp_path / CONFIG_FILENAME, uncommented + "\n")
    declared = read_config(path)
    for setting in SETTINGS:
        if setting.default is not None:
            assert declared[setting.name] == setting.default
