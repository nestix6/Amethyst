# Amethyst

[![CI](https://github.com/nestix6/Amethyst/actions/workflows/ci.yml/badge.svg)](https://github.com/nestix6/Amethyst/actions/workflows/ci.yml)

Turn a Markdown file into a well-typeset PDF or Word document.

```sh
amethyst convert notes.md -o notes.pdf
amethyst convert notes.md -f docx
```

One file in, one styled document out. No flags required, no stylesheet to
write, no reference `.docx` to maintain. The point is output that looks
deliberately typeset rather than printed from a browser — and a shared theme,
so the same source reads as the same document in both formats.

This page is the quick tour. **[Full documentation](docs/documentation.md)**
covers every option, the theme format, the configuration layers and the
architecture.

---

## Install

Amethyst is a Python 3.10+ package. Install it as a tool:

```sh
uv tool install amethyst
```

or into an environment of your own with `pip install amethyst`.

**The PDF path needs Pango**, which is a system library rather than a Python
one. That is the only thing Amethyst cannot install for you:

```sh
# macOS
brew install pango

# Debian / Ubuntu
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
```

DOCX output needs none of it. If Pango is missing, `amethyst convert -f docx`
still works and `-f pdf` exits 3 with a line saying what to install, rather
than a `cffi` traceback.

---

## Use

```sh
amethyst convert report.md -f pdf                    # writes report.pdf
amethyst convert report.md -f docx                   # writes report.docx
amethyst convert report.md -o ~/Desktop/review.pdf   # the extension picks the format
amethyst convert report.md -f pdf --toc --title-page # contents and a cover
amethyst convert - -f pdf -o - < report.md           # stdin to stdout
```

The format has to be stated, by `-f` or by an output path that ends in `.pdf`
or `.docx` — or once, in a config file. Given `-f` and no `-o`, the output is
the input path with the extension swapped. With `-o -` the document goes to
stdout and every message steps aside to stderr, so the bytes stay clean in a
pipeline.

### Options

| Flag | Effect |
| --- | --- |
| `-o, --output PATH` | Output file; the extension infers the format. `-` is stdout. |
| `-f, --format pdf\|docx` | Explicit format. Required when `-o` is omitted or is stdout. |
| `-t, --theme NAME\|PATH` | A builtin theme name, or a path to a theme `.toml`. |
| `--css PATH` | Extra stylesheet, appended last. PDF only. |
| `--toc` | Open the document with a table of contents. |
| `--toc-depth N` | Heading levels the contents lists. Default 3. |
| `--title-page` | Open with a title page built from the frontmatter. |
| `--title TEXT`, `--author TEXT` | Override what the frontmatter declared. |
| `--page-size TEXT` | `A4`, `Letter`, or a CSS size. Defaults to the theme's. |
| `--margin TEXT` | CSS-style: `2cm`, or `2cm 2.5cm`. Defaults to the theme's. |
| `--no-page-numbers` | Suppress the footer numbering. |
| `--no-remote` | Never download an image; leave a gap where a remote one was. |
| `--highlight-style NAME` | Any Pygments style, or `none` to leave code uncoloured. |
| `--pdf-engine NAME` | `weasyprint`. The flag exists to keep the seam visible. |
| `-q, --quiet` / `--verbose` | Errors only / detail, and tracebacks on failure. |

Two more commands:

```sh
amethyst themes list        # the builtin themes, with a line about each
amethyst themes show NAME   # a theme's TOML, ready to copy and edit
amethyst init               # write a starter amethyst.toml here
```

`amethyst --version` prints the version. Exit codes are distinct so the tool
composes in scripts: **0** ok, **1** conversion failure, **2** bad usage,
**3** a missing system dependency.

---

## What converts

Everything below works in **both** formats unless the note says otherwise.

Headings, bold, italic, strikethrough, inline code, hard breaks, nested and
ordered lists, task lists, blockquotes, GFM tables, horizontal rules, links,
local images, remote images, fenced code with syntax highlighting, footnotes,
a table of contents, page numbers, a running head, a title page, and document
metadata. PDFs also get nested outline bookmarks, straight from the headings.

Three things are deliberately approximate:

- **Footnotes in Word** are an endnote-style list at the end of the document,
  not real Word footnotes.
- **Task lists in Word** are printed ☐ / ☑ glyphs, not clickable checkboxes.
- **Raw HTML** passes through to PDF and is skipped in DOCX, with one warning
  naming the line it was on.

LaTeX math and Mermaid diagrams are out of scope.

---

## Frontmatter

YAML frontmatter sets the document's metadata. It reaches the title page, the
running head, the PDF's info dictionary and Word's core properties.

```markdown
---
title: Quarterly Review
subtitle: What the numbers did
author: Ada Lovelace
date: 2026-03-31
keywords: [finance, review]
---
```

`title` falls back to the first `h1` if it is not declared. A `date` that is
not a real date — "Spring 2026" — still prints on the cover, but does not
reach the file's timestamp metadata.

Frontmatter may also set any option from the table above except `format`,
which has to be settled before the document is opened:

```markdown
---
title: Quarterly Review
theme: academic
toc: true
---
```

---

## Configuration

Settings resolve in this order, later winning:

```
builtin defaults → ~/.config/amethyst/config.toml → ./amethyst.toml
                 → the document's frontmatter → command-line flags
```

`amethyst init` writes a starter `./amethyst.toml` with every setting listed,
defaulted and commented out. `./` means the working directory, not the
document's — `init` writes there and `convert` reads there, so the two agree.

A flag you did not type does not overrule the config file, only one you did.
And a path named inside a config file resolves against that file, so a
stylesheet named in `~/.config/amethyst/config.toml` means the one beside it.

---

## Themes

A theme is one TOML file declaring fonts, a type scale, colours, spacing and
page geometry. It compiles two ways — to CSS custom properties for the PDF,
and to Word style definitions for the DOCX — which is what keeps the two
outputs looking like the same document.

Three ship: `default` (a serif face and a violet accent), `academic` (a quiet
book serif, a narrow measure, generous margins) and `github` (system sans,
blue links, quiet rules).

To write your own, start from a builtin and change what you want:

```sh
amethyst themes show default > house.toml
amethyst convert report.md -t house.toml
```

Anything a theme leaves out is taken from `default`, so a theme can be one
section — or one line:

```toml
description = "House style."

[fonts]
body = ["Charter", "Georgia", "serif"]

[colors]
accent = "#0b6e4f"

[type]
size = 10.5

[page]
size = "Letter"
margin = "1in 1.25in"
```

Sizes are numbers, not CSS lengths: `size = 11` is points, and everything else
(`headings`, `spacing`, `code`, `title`) is a multiple of it — so changing
`size` alone rescales the whole document. Colours are hex, because a Word
style cannot take any other notation.

---

## Remote images

An image with an `http(s)` URL is downloaded once, before either renderer
starts, and cached under `~/.cache/amethyst/images` — `XDG_CACHE_HOME` is
honoured. A second conversion of the same document makes no request.
`--no-remote` turns it off, and a fetch that fails warns and leaves a gap
rather than stopping the conversion.

Amethyst opens a socket in exactly one place, and only for this.

---

## Development

```sh
uv sync
uv run amethyst convert tests/fixtures/kitchen-sink.md -o out.pdf
```

Four checks, all of which should be clean:

```sh
uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/amethyst
```

`tests/fixtures/kitchen-sink.md` exercises every feature in the table above
and is converted to both formats by the suite. The suite is offline by
construction — a test that reaches the network fails rather than waiting on a
socket — and PDF tests skip with a clear message when Pango is absent.

The one thing tests cannot check is whether a page *looks* right: extracted
text and page counts cannot see layout. Both rendering defects found while
building the PDF path passed every assertion. So look at the output after
changing any CSS.

---

## Licence

MIT. See [LICENSE](LICENSE).
