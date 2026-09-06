# Amethyst — Documentation

Amethyst is a command-line tool that turns a Markdown file into a well-typeset
PDF or Word document. One file in, one styled document out.

This is the complete reference. For a five-minute introduction, read the
[README](../README.md) instead.

---

## Contents

- [Installation](#installation)
- [Concepts](#concepts)
- [Commands](#commands)
  - [`amethyst convert`](#amethyst-convert)
  - [`amethyst themes list`](#amethyst-themes-list)
  - [`amethyst themes show`](#amethyst-themes-show)
  - [`amethyst init`](#amethyst-init)
- [Configuration](#configuration)
- [Frontmatter](#frontmatter)
- [Themes](#themes)
- [Markdown support](#markdown-support)
- [Syntax highlighting](#syntax-highlighting)
- [Document furniture](#document-furniture)
- [Images](#images)
- [Exit codes and errors](#exit-codes-and-errors)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)

---

## Installation

Amethyst needs Python 3.10 or newer. It is tested on 3.10, 3.11, 3.12 and 3.13.

```sh
uv tool install amethyst-cli
```

Or into an environment you manage yourself:

```sh
pip install amethyst-cli
```

The command it installs is `amethyst`, and the import package is `amethyst`
too — only the name you install differs.

### The one system dependency

**PDF output needs Pango**, a text-shaping library that WeasyPrint loads
through cffi at render time. It cannot be installed from PyPI.

```sh
# macOS
brew install pango

# Debian / Ubuntu
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0

# Fedora
sudo dnf install pango
```

**DOCX output needs none of it.** On a machine with no Pango, `amethyst --help`
and `amethyst convert -f docx` work normally, and only `-f pdf` fails — with
one line naming what to install, and exit code 3. See
[Troubleshooting](#troubleshooting).

Nothing else is required. Install guides for WeasyPrint often mention `libffi`
as well; that is a holdover from when pip compiled `cffi` from source, and the
`cffi` wheel is prebuilt now.

---

## Concepts

Four ideas explain most of Amethyst's behaviour.

**Two pipelines, one theme.** PDF is produced by rendering Markdown to HTML and
laying it out with CSS Paged Media. DOCX is produced by walking the Markdown
token stream directly into Word paragraphs, runs and styles. These are
genuinely different routes — Word has no HTML+CSS layer to borrow. What keeps
the two outputs looking like the same document is the theme, which compiles two
ways: to CSS custom properties for one, and to Word style definitions for the
other. See [Architecture](#architecture).

**Specific beats general.** Every setting can be stated in several places, and
the one closest to this particular conversion wins. A flag beats the document's
frontmatter, which beats a config file in the directory, which beats your
personal config file, which beats the built-in default. See
[Configuration](#configuration).

**The conversion never blocks on the network by surprise.** Remote images are
downloaded in one step, before either renderer starts, with a timeout and a
size cap; after that step every image the renderer can see is a file on disk.
`--no-remote` turns the step off entirely. See [Images](#images).

**Warn, don't die.** A missing image, a construct Word cannot hold, an
unrecognised code fence — each produces one warning naming the source line and
the conversion continues. Only something that makes a document impossible is an
error.

---

## Commands

```
amethyst [--version] COMMAND [ARGS]...
```

| Command | What it does |
| --- | --- |
| `convert` | Convert a Markdown file to PDF or DOCX. |
| `themes list` | List the builtin themes. |
| `themes show NAME` | Print a theme's TOML, ready to copy and edit. |
| `init` | Write a starter `amethyst.toml` into the current directory. |

`amethyst --version` prints the version and exits.

Shell completion is deliberately not installed. The completions worth having —
theme names, Pygments style names — need explicit callbacks that do not exist
yet, and Typer's completion machinery cannot be half-enabled.

---

### `amethyst convert`

```
amethyst convert INPUT [OPTIONS]
```

`INPUT` is a path to a Markdown file, or `-` to read stdin.

#### Choosing the output

| Option | Description |
| --- | --- |
| `-o`, `--output PATH` | Where to write. The extension infers the format. `-` writes to stdout. |
| `-f`, `--format {pdf,docx}` | The output format, explicitly. |

The format must be settled one of three ways: by `-f`, by an output path ending
in `.pdf` or `.docx`, or by `format` in a config file. Amethyst does **not**
default to PDF — `amethyst convert notes.md` with neither flag is a usage error
(exit code 2).

Precedence among the three, most specific first:

1. `-f` always wins. If it disagrees with the output extension you get a
   warning, not an error — you said what you meant.
2. An output path's extension beats a configured format, because `-o out.docx`
   is about this invocation and a config file is about every one.
3. A configured `format` applies when nothing else says.

If `-o` is omitted, the output is the input path with its extension swapped.
Reading from stdin therefore requires an explicit `-o`, since there is no input
path to swap.

**Writing to stdout.** With `-o -` the document's bytes go to stdout and every
human-readable line — warnings, the "wrote …" confirmation, the verbose plan —
moves to stderr, so a pipeline gets a clean file:

```sh
amethyst convert notes.md -f pdf -o - > notes.pdf
cat notes.md | amethyst convert - -f docx -o - > notes.docx
```

#### Appearance

| Option | Default | Description |
| --- | --- | --- |
| `-t`, `--theme NAME\|PATH` | `default` | A builtin theme name, or a path to a theme `.toml`. |
| `--css PATH` | — | An extra stylesheet, appended after everything else so it wins. **PDF only.** |
| `--page-size TEXT` | the theme's | `A4`, `Letter`, or any CSS page size. |
| `--margin TEXT` | the theme's | CSS-style margin: `2cm`, or `2cm 2.5cm`. |
| `--highlight-style NAME` | `default` | Any Pygments style name, or `none`. |

`--page-size` and `--margin` default to *nothing* rather than to a value: a
theme declares the page it wants, and these override the theme that declared
it. Passing neither is not the same as passing `A4`.

Passing `--css` with `-f docx` warns and ignores it — but only if you typed the
flag. A config file that names a stylesheet for a directory of documents is not
making a mistake every time one of them is converted to Word, so that case is
silent.

#### Document furniture

| Option | Default | Description |
| --- | --- | --- |
| `--toc` | off | Open the document with a table of contents. |
| `--toc-depth N` | `3` | Heading levels the contents lists, 1 to 6. |
| `--title-page` | off | Open with a title page built from the frontmatter. |
| `--title TEXT` | — | Override the frontmatter title. |
| `--author TEXT` | — | Override the frontmatter author. |
| `--no-page-numbers` | — | Suppress the footer page numbers. |

`--title` and `--author` override the document's metadata itself, so they reach
the title page, the running head, the PDF info dictionary and Word's core
properties alike.

#### Behaviour

| Option | Default | Description |
| --- | --- | --- |
| `--no-remote` | — | Never download an image over the network. |
| `--pdf-engine NAME` | `weasyprint` | The PDF backend. |
| `-q`, `--quiet` | — | Print nothing but errors. |
| `--verbose` | — | Print the resolved settings, and tracebacks on failure. |

`--pdf-engine` accepts one value today. The flag exists so that the seam is
visible and a second engine can be added without changing the CLI's shape.

`--quiet` and `--verbose` together are a usage error.

#### `--verbose` output

Under `--verbose`, Amethyst prints every value it resolved before it starts
work, which is the fastest way to find out why a document came out unexpectedly:

```
Converting:
          input  report.md
         output  report.pdf
         format  pdf
          theme  academic
         config  /Users/you/.config/amethyst/config.toml, amethyst.toml
          title  Quarterly Review
         author  Ada Lovelace
            toc  depth 2
     title page  yes
      page size  A4
         margin  2.5cm 3cm
   page numbers  yes
   highlighting  default
  remote images  yes
     pdf engine  weasyprint
```

---

### `amethyst themes list`

Prints each builtin theme with its one-line description.

```sh
$ amethyst themes list
academic  A quiet book serif, a narrow measure and generous margins.
default   A serif text face, roomy leading and a violet accent.
github    GitHub's Markdown look: system sans, blue links, quiet rules.
```

---

### `amethyst themes show`

Prints a theme's TOML exactly as written, including its comments, so it can be
redirected to a file and edited.

```sh
amethyst themes show academic > house.toml
```

The output is deliberately not styled or wrapped: colours like `#6a3fa0` would
otherwise be read as terminal markup, and a folded long line would put a
newline inside the TOML. The result parses as a theme at any terminal width.

---

### `amethyst init`

Writes a starter `amethyst.toml` into the **current working directory**, with
every setting listed, documented and commented out at its real default.

```sh
$ amethyst init
wrote amethyst.toml
```

It refuses to overwrite an existing file. The starter file is generated from
the same schema the settings are validated against, so it cannot promise a
default the code does not have.

---

## Configuration

### Resolution order

Later wins:

```
1. builtin defaults
2. ~/.config/amethyst/config.toml     how this person's documents look
3. ./amethyst.toml                    how these documents look
4. the document's frontmatter         how this document looks
5. command-line flags                 how this conversion looks
```

The principle: the further a statement is from the document, the more general
it is, and the thing said closest to the moment of conversion wins.

Two details are worth knowing.

**`./` is the working directory, not the document's.** `amethyst init` writes
there and `convert` reads there, so the two always agree. A config file that
followed the source file around would be a different feature.

**A flag you did not type does not overrule a config file.** Amethyst asks
Click which parameters actually came from the command line rather than
comparing values against defaults — which cannot tell `--toc-depth 3` from
silence. Without this, every flag would silently overrule the config file with
its own default.

`XDG_CONFIG_HOME` is honoured for the user config file's location.

### Settings

Every setting below can appear in a config file. All but `format` can also
appear in a document's frontmatter.

| Setting | Type | Default | Meaning |
| --- | --- | --- | --- |
| `format` | `"pdf"` \| `"docx"` | — | Output format when the output path does not imply one. **Config file only.** |
| `theme` | string | `"default"` | Builtin theme name, or a path to a theme `.toml`. |
| `css` | string | — | Extra stylesheet, appended after everything else. PDF only. |
| `toc` | boolean | `false` | Open the document with a table of contents. |
| `toc_depth` | integer 1–6 | `3` | Heading levels the contents lists. |
| `title_page` | boolean | `false` | Open with a title page built from frontmatter. |
| `page_size` | string | the theme's | Sheet size: `A4`, `Letter`, or a CSS size. |
| `margin` | string | the theme's | Page margin, CSS style. |
| `page_numbers` | boolean | `true` | Number the pages in the footer. |
| `highlight_style` | string | `"default"` | Pygments style for code, or `none`. |
| `remote` | boolean | `true` | Download images the document links to. |

An example `amethyst.toml`:

```toml
theme = "academic"
toc = true
toc_depth = 2
title_page = true
highlight_style = "friendly"
margin = "2.5cm 3cm"
```

### Why frontmatter cannot set `format`

A document may reasonably say how it should look. Where its output file goes is
the invocation's business. There is also a practical reason: the format has to
be settled *before* the document is opened, or `amethyst convert -` with no
`-o` would block reading stdin before it could tell you what is wrong.

### Validation

A config file is checked strictly. An unknown key is an error naming the file
and listing what a config file takes — silently ignoring a misspelled key looks
exactly like a setting that does not work. A value of the wrong type is refused
rather than coerced: a page size written as a number is a mistake, not a size.

Frontmatter is checked loosely, and has to be: an unknown key there is a title
or a keyword list, not a mistake. Only keys that name a setting are read.

### Paths inside config files

A path declared in a config file resolves against **that file**, not the working
directory. A stylesheet named in `~/.config/amethyst/config.toml` means the one
beside it. The same applies to a `theme` that names a file — but a bare word is
a builtin theme name and is left alone, while a bare word for `css` is still a
filename.

---

## Frontmatter

YAML frontmatter at the top of the document, between `---` lines, sets the
document's metadata. Keys are lowercased, so `Title:` and `title:` mean the
same thing.

```markdown
---
title: Quarterly Review
subtitle: What the numbers did
author: Ada Lovelace
date: 2026-03-31
keywords: [finance, review]
---

# Quarterly Review
```

| Key | Where it goes |
| --- | --- |
| `title` | The title page, the running head's left side, PDF `/Title`, Word's title property. Falls back to the first `h1`. |
| `subtitle` | The title page, PDF `/Subject`, Word's subject property. |
| `author` | The title page, PDF `/Author`, Word's author property. A YAML list becomes a comma-separated string. |
| `date` | The title page, and — if it parses as a real date — the file's creation timestamp. |
| `keywords` | PDF `/Keywords`, Word's keywords property. A list becomes comma-separated. |

A `date` that is not a real date — `Spring 2026` — still prints on the cover but
does not reach the timestamp metadata, which needs an actual date.

Frontmatter may also carry any setting from the [table above](#settings) except
`format`:

```markdown
---
title: Quarterly Review
theme: academic
toc: true
title_page: true
---
```

Frontmatter that parses but is not a mapping — a YAML list, say — is an error
rather than a warning. Silently dropping a document's title and carrying on is
worse than stopping with one clear line.

---

## Themes

A theme is a single TOML file declaring fonts, a type scale, colours, spacing
and page geometry. It is the mechanism that keeps PDF and DOCX output looking
like the same document: it compiles to CSS custom properties for the PDF path
and to Word style definitions for the DOCX path, and neither renderer holds an
opinion about a font or a colour.

### The builtin themes

| Name | Description |
| --- | --- |
| `default` | A serif text face, roomy leading and a violet accent. |
| `academic` | A quiet book serif, a narrow measure and generous margins. |
| `github` | GitHub's Markdown look: system sans, blue links, quiet rules. |

### Writing your own

Start from a builtin and change what you want:

```sh
amethyst themes show default > house.toml
amethyst convert report.md -f pdf -t house.toml
```

**Anything a theme leaves out is filled in from `default`**, so a theme can be
one section — or one line. There is no such thing as an incomplete theme.

```toml
description = "House style."

[fonts]
body = ["Charter", "Georgia", "serif"]

[colors]
accent = "#0b6e4f"

[page]
size = "Letter"
margin = "1in 1.25in"
```

### Theme reference

#### `description`

A one-line string, shown by `amethyst themes list`.

#### `[fonts]`

Three stacks, most-preferred family first. The last entry should be a generic
CSS family so there is always something to fall back to.

| Key | Meaning |
| --- | --- |
| `body` | Body text. |
| `heading` | Headings, and the title on a cover. |
| `mono` | Code blocks and inline code. |

The PDF uses the whole stack. Word can hold only one name per style, so the
first non-generic family is used — a generic name like `ui-monospace` would be
read by Word as a font nobody has, and code would quietly set in the body face.

Family names may not contain `;`, `{`, `}`, `<`, `>`, quotes, backslashes or
`/*`, because they are written into a stylesheet.

#### `[type]`

| Key | Type | Meaning |
| --- | --- | --- |
| `size` | points | Body text size. Everything relative scales with it. |
| `small` | points | Footnotes, table cells, page furniture. |
| `code` | multiple of `size` | Code blocks and inline code. |
| `title` | multiple of `size` | The title on a title page. |
| `line_height` | multiple of the font size | Leading. |
| `heading_weight` | 100–900 | CSS font weight for headings. |
| `headings` | list of 6 multiples | h1 to h6, in order. All six are required. |

**Sizes are bare numbers, not CSS lengths.** The two absolute ones are points,
because that is what print measures in and what Word wants; everything else is
a multiple of `size`, so changing `size` alone rescales the whole document and
neither compiler has to parse a unit out of a string.

`title` is its own setting rather than the `h1` size on purpose: a cover whose
title is exactly the size of the heading on the next page reads as a heading
that was given a page to itself.

#### `[colors]`

Hex, three or six digits, with or without the leading `#`. Nothing else — CSS
would accept any colour notation, and a Word style needs three bytes.

| Key | Used for |
| --- | --- |
| `text` | Body text. |
| `muted` | Footnotes, page numbers, quoted text, `h6`. |
| `accent` | Links. |
| `rule` | Borders and horizontal rules. |
| `fill` | Code and table-header backgrounds. |

#### `[spacing]`

Multiples of the body size.

| Key | Meaning |
| --- | --- |
| `block` | The gap after a paragraph, list, table or code block. |
| `indent` | How far a list or a definition is indented. |

#### `[page]`

The exception to "no CSS": both values are paged-media descriptors and are
passed through as written.

| Key | Example |
| --- | --- |
| `size` | `"A4"`, `"Letter"`, `"210mm 297mm"` |
| `margin` | `"2cm"`, `"2cm 2.5cm"`, `"1in 1.25in 1in 1.25in"` |

The Word side reads what it can of a CSS margin and warns when it cannot, since
Word measures in EMU and has no concept of `em` or a percentage.

### Validation

A theme is validated when it is loaded, and an unknown key is refused —
`default.toml` *is* the schema, so anything not in it is a typo. A theme that
cannot be found is a usage error (exit 2); a theme that is found but will not
parse or validate is a conversion failure (exit 1). Those are different
mistakes and deserve different exit codes.

---

## Markdown support

Amethyst parses CommonMark plus GitHub Flavored Markdown (tables,
strikethrough, autolinking) through markdown-it-py, with plugins for
frontmatter, footnotes, definition lists, task lists and heading anchors.

| Feature | PDF | DOCX | Notes |
| --- | :---: | :---: | --- |
| Headings `h1`–`h6` | ✅ | ✅ | Mapped to Word's `Heading 1`–`6`. |
| Bold, italic, strikethrough | ✅ | ✅ | |
| Inline code | ✅ | ✅ | |
| Paragraphs, hard breaks | ✅ | ✅ | |
| Lists, nested and ordered | ✅ | ✅ | Word: `List Bullet N` / `List Number N`. |
| Ordered lists with a start | ✅ | ✅ | `4.` starts at four in both. |
| Task lists | ✅ | ⚠️ | Word gets printed ☐ / ☑ glyphs, not real checkboxes. |
| Definition lists | ✅ | ✅ | |
| Fenced code | ✅ | ✅ | Highlighted in both, from one style. |
| Blockquotes | ✅ | ✅ | Word: `Quote` style, left-ruled and indented. |
| Tables (GFM) | ✅ | ✅ | Header row repeats across pages. |
| Horizontal rules | ✅ | ✅ | Word: a bottom-bordered empty paragraph. |
| Links | ✅ | ✅ | Internal `#anchor` links work in both. |
| Images, local | ✅ | ✅ | Resolved relative to the source file. |
| Images, remote | ✅ | ✅ | Fetched and cached before rendering. |
| Images, `data:` URI | ✅ | ❌ | Word skips it with a warning. |
| Footnotes | ✅ | ⚠️ | Word gets an endnote-style list at the end. |
| Table of contents | ✅ | ✅ | PDF: generated. Word: a real `TOC` field. |
| Page numbers, running head | ✅ | ✅ | CSS margin boxes / OOXML field codes. |
| Title page | ✅ | ✅ | `--title-page`, from frontmatter. |
| Document metadata | ✅ | ✅ | PDF info dictionary / Word core properties. |
| PDF outline bookmarks | ✅ | n/a | Automatic, and correctly nested. |
| Raw HTML | ⚠️ | ❌ | PDF: passed through. Word: skipped with a warning. |
| LaTeX math | ❌ | ❌ | Out of scope. |
| Mermaid diagrams | ❌ | ❌ | Out of scope. |

### Known approximations

**Footnotes in Word** are an endnote-style list at the end of the document
rather than real Word footnotes, separated by a rule and numbered to match
their references.

**Task lists in Word** print ☐ and ☑ glyphs and take a list's indent without
its bullets. They are not clickable checkboxes.

**Raw HTML in Word** is skipped, with one warning naming the line. An HTML
comment is skipped silently, since it was never going to be visible.

**A list item whose first block is not a paragraph** — `- ` followed
immediately by a fenced code block — indents correctly in Word but loses its
bullet.

### An escaping trap worth knowing

An unescaped space breaks an image outright, at the parser level:
`![a](my image.png)` produces no image token at all. Percent-encode it as
`my%20image.png`. Amethyst decodes the reference before touching the
filesystem, so the encoded form finds the real file.

---

## Syntax highlighting

Code is highlighted with Pygments, in **both** formats, from one style.

```sh
amethyst convert notes.md -f pdf --highlight-style monokai
amethyst convert notes.md -f docx --highlight-style none
```

Any Pygments style name works; `none` turns colour off and leaves code set in
the mono face. An unknown name is a usage error listing what is available.

Pygments' own stylesheet generator is not used. It emits rules for line
numbering that nothing here writes, and a `pre { line-height: 125% }` that
would quietly override the theme's leading — a highlighting style should colour
the code, not re-typeset it. Instead a style is reduced to a colour, a weight
and a slope per token class, and both pipelines read *that*. It is why a
keyword is the same colour in the PDF and in Word.

**A dark style brings its own background; a light one keeps the theme's.**
Monokai's colours are chosen against `#272822` and are illegible on a light
fill. The decision is made from the style's own background luminance, and it
applies to every code block in the document — including blocks the highlighter
could not colour, which would otherwise be a light box a paragraph away from a
dark one.

**Nothing is guessed.** A fence with no language, or one Pygments does not
recognise, is set plain rather than passed to a language guesser. Guessing is
slow, and when it is wrong it is wrong in colour. Each unrecognised language is
warned about once, however many blocks use it.

**Inline code is never highlighted.** Three words between backticks name no
language. It keeps the theme's fill even when the blocks around it are dark,
because it belongs to the sentence it sits in rather than to a panel.

---

## Document furniture

"Furniture" is what goes on the page besides the document: the contents, the
running head, the cover, the page numbers. Both formats have to agree about
*what* it says even though they build it in completely different ways, so those
decisions are made once and neither renderer decides any of them.

### Table of contents

`--toc` opens the document with a contents listing every heading down to
`--toc-depth` (default 3, maximum 6). Deeper headings are dropped rather than
flattened.

In the **PDF** it is generated, with dot leaders and page numbers resolved by
CSS `target-counter()`.

In the **DOCX** it is a real Word `TOC` field with its result already written
in — each entry a hyperlink to the heading's bookmark, a dotted tab and a page
reference. Word rebuilds it against its own pagination when the file opens, so
it stays correct as the document is edited, and a reader that shows a field's
stored result rather than evaluating it still sees a contents.

> **Note.** A DOCX containing a `TOC` field makes Word ask *"This document
> contains fields that may refer to other files. Do you want to update the
> fields in this document?"* on open. That is the price of a contents that
> maintains itself; without it the entries have dot leaders and no page
> numbers. Documents converted without `--toc` raise no dialog.

### Running head

Automatic, in both formats. The left side carries the document's title; the
right side names the current section.

**The head tracks the shallowest heading level that occurs more than once.**
For the ordinary shape of a Markdown file — one `h1` naming the document, `h2`
sections under it — that is the `h2`, which is the level that actually changes
as you turn the pages. A document of `h1` chapters gets its chapters. A
document where no level repeats gets no section name at all, because a head
naming the only heading in the document is the title written twice.

The opening page of a document carries no running head.

### Title page

`--title-page` opens with a cover carrying the title, subtitle, author and
date from the frontmatter. It is opt-in rather than automatic, deliberately: a
cover page on a two-page memo is wrong, and a document whose frontmatter title
repeats its first heading — the common case — would get the same words twice on
facing pages.

Without a `title` there is nothing worth printing, so the cover is skipped and
Amethyst says so. A cover carries no running head and no page number.

Front matter — the cover and the contents — is a named page in CSS and a
separate section in Word, which is what lets it carry different furniture from
the body.

### Page numbers

On by default, centred in the footer, in the theme's `small` size and `muted`
colour. `--no-page-numbers` suppresses them in both formats.

### PDF bookmarks

Every PDF gets a nested outline built from its headings, automatically. There is
no flag and no way to turn it off.

---

## Images

### Local images

An image path is resolved relative to the **source file's directory** — or the
working directory when reading from stdin. The rewrite happens only when the
file actually exists; a missing file is left exactly as the author wrote it, so
the warning names their reference rather than one Amethyst invented:

```
warning: image not found: diagrams/flow.png (line 42)
```

A missing image is never fatal. The document converts with a gap where the
picture was.

### Remote images

An image with an `http` or `https` URL is downloaded **before either renderer
starts**, so by the time rendering begins every image is a file on disk. This
is the only place in Amethyst that opens a socket.

The limits are deliberately unfriendly, because a document is a document and
not a browser:

| Limit | Value |
| --- | --- |
| Timeout | 10 seconds per image |
| Maximum size | 32 MB per image |
| Allowed schemes | `http`, `https` — rechecked after redirects |
| Concurrency | one connection at a time |

**Downloads are cached** under `~/.cache/amethyst/images`, keyed by URL, so
converting the same document twice — or a dozen documents sharing a logo —
makes one request. `XDG_CACHE_HOME` is honoured. The cache is never
invalidated: an image at a URL is treated as the thing that URL names. Delete
the directory to clear it.

`--no-remote` (or `remote = false`) skips the step entirely. A failed or skipped
download warns and leaves a gap; it never stops the conversion.

### Data URIs

A `data:` URI is embedded in the **PDF** untouched — it needs no resolving and
no fetch. **Word cannot hold one**, so the DOCX path warns and leaves a gap:

```
warning: image skipped: data:image/png;base64,iVBORw0… (line 3) — it could not be read.
```

If a document has to convert to both formats, put the image in a file.

---

## Exit codes and errors

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Conversion failure — a broken theme, an unreadable document, an unwritable output path. |
| `2` | Bad usage — a missing format, an unknown theme, contradictory flags. |
| `3` | A missing system dependency (in practice, Pango). |

The codes are distinct so the tool composes in scripts:

```sh
if ! amethyst convert notes.md -f pdf; then
    case $? in
        2) echo "check the command line" ;;
        3) echo "install pango" ;;
        *) echo "conversion failed" ;;
    esac
fi
```

### Error output

A user error is one line on stderr, plus a hint when there is something
concrete to suggest — never a traceback:

```
error: Unknown theme 'acadmic'.
hint: Builtin themes: academic, default, github.
```

`--verbose` adds the traceback. An unexpected exception — a bug — says so, and
says that it is not something you did.

The theme rules are worth restating because they split across two codes: a
theme that cannot be **found** (an unknown builtin name, or a path with no file
at it) is bad usage, exit 2. A theme that is found but will not **parse or
validate** is a conversion failure, exit 1.

---

## Architecture

```
                        input.md
                            │
              ┌─────────────▼─────────────┐
              │  parse layer              │
              │  frontmatter split        │
              │  markdown-it-py (GFM)     │
              │  asset path resolution    │
              └─────────────┬─────────────┘
                            │
                  token stream + metadata
                            │
                    remote image fetch
                            │
              ┌─────────────┴─────────────┐
              │                           │
     ┌────────▼────────┐        ┌─────────▼─────────┐
     │  HTML renderer  │        │   DOCX renderer   │
     │  (markdown-it)  │        │  token walker →   │
     │        ↓        │        │   python-docx     │
     │  WeasyPrint     │        │                   │
     └────────┬────────┘        └─────────┬─────────┘
              │                           │
           out.pdf                     out.docx
              │                           │
              └───────────┬───────────────┘
                          │
                 ┌────────▼────────┐
                 │  Theme (TOML)   │
                 │ fonts, scale,   │
                 │ colours, page   │
                 │ → CSS  → styles │
                 └─────────────────┘
```

### Why two pipelines

PDF has a mature HTML+CSS route. CSS Paged Media gives page margins, running
headers, page numbers, TOC page references and PDF bookmarks nearly for free;
reimplementing that against a low-level PDF library is weeks of work.

Word has no such route. Its format is a flow of styled paragraphs and runs, so
it needs a direct walk of the token stream. Forcing a shared abstraction over
two formats this different would cost more than it saved.

**The theme is the consistency mechanism**, and it is the only one. Everything
that must look the same in both formats is declared there once and compiled
twice.

### Module layout

```
src/amethyst/
├── cli.py            Typer app, argument resolution, exit codes
├── config.py         settings schema, file discovery, the merge
├── document.py       Document: metadata + tokens + source directory
├── errors.py         the error hierarchy, each carrying its exit code
├── ooxml.py          raw-XML helpers; under neither pipeline
├── remote.py         download + cache; the only socket in the project
├── parse/
│   ├── markdown.py   the one parser both pipelines share
│   ├── frontmatter.py
│   └── assets.py     resolve image and link paths
├── theme/
│   ├── __init__.py   dataclasses, loader, validation
│   ├── to_css.py     Theme → CSS custom properties
│   ├── to_docx.py    Theme → python-docx style definitions
│   └── builtin/      the shipped themes, and base.css
└── render/
    ├── base.py       the renderer protocol and RenderOptions
    ├── furniture.py  contents, running head, cover — shared decisions
    ├── html.py       tokens → one standalone HTML document
    ├── pdf.py        HTML → PDF, engine dispatch, Pango diagnosis
    ├── docx.py       the token walker
    └── highlight.py  Pygments, compiled two ways
```

Three modules sit under neither pipeline, and that is the point.

**`ooxml.py`** holds the raw XML that python-docx has no API for — hyperlinks,
field codes, shading, bookmarks, borders, repeating table headers, numbering
instances. Both the Word renderer and the theme's Word compiler need the same
elements, since Word styles are themselves XML. Nothing in it imports from
Amethyst.

**`render/furniture.py`** holds the decisions both formats must make
*identically*: which headings the contents lists, which level the running head
tracks, what is on the cover. A difference between two pipelines is invisible in
a test of either one, so these are pure functions with their own tests and
neither renderer decides any of it.

**`remote.py`** runs as a step of the conversion, before either renderer
starts, which is what keeps the cache, the timeout and the size limit from
being written twice.

### Dependencies

| Package | Why |
| --- | --- |
| `markdown-it-py` | CommonMark parsing, and the token stream the Word walker needs. |
| `mdit-py-plugins` | Frontmatter, footnotes, definition lists, task lists, anchors. |
| `linkify-it-py` | Hard-required by the `gfm-like` preset, at render time. |
| `weasyprint` | HTML + CSS Paged Media → PDF. |
| `python-docx` | Word paragraphs, runs, styles, tables, images. |
| `pygments` | Syntax highlighting for both formats. |
| `typer`, `rich` | The CLI and its output. |
| `pyyaml` | Frontmatter. |
| `tomli` | TOML on Python 3.10, where `tomllib` is not yet stdlib. |

---

## Troubleshooting

### `error: PDF output needs Pango, which is not installed.` (exit 3)

Install it: `brew install pango` on macOS, or your distribution's Pango
packages. Or convert to Word instead, which needs nothing.

### `error: Pango is installed in …, but WeasyPrint could not load it from there.` (exit 3)

Pango is present and Amethyst has already pointed the loader at it, so the
usual cause is an architecture mismatch — Homebrew's libraries built for one of
arm64 or x86_64 and your Python for the other. Check that `brew config` and
`python -c "import platform; print(platform.machine())"` agree.

You do **not** need to export `DYLD_FALLBACK_LIBRARY_PATH`. Amethyst puts
Homebrew's lib directory on the loader path itself, in-process, immediately
before importing WeasyPrint. Exporting it in a shell would not work anyway:
the installed console script is a `/bin/sh` wrapper, and macOS strips every
`DYLD_*` variable when it executes a system-protected binary.

### `error: No output format given.` (exit 2)

Amethyst does not default to PDF. Pass `-f pdf`, name the output `-o out.pdf`,
or set `format = "pdf"` in a config file.

### `error: Writing to stdout needs an explicit format.` (exit 2)

`-o -` gives no extension to infer from. Add `-f`.

### `error: Reading from stdin needs an explicit output path.` (exit 2)

There is no input path whose extension can be swapped. Add `-o out.pdf`, or
`-o -` to write the document to stdout.

### `warning: image not found: …`

The path is resolved relative to the source file, not the working directory.
Check that the reference is right from the document's own directory — and that
any space in the filename is percent-encoded as `%20`, since an unescaped space
stops the image being parsed as an image at all.

### `warning: raw HTML is not converted to Word; skipped it (line N)`

Expected. Word has no way to hold arbitrary HTML. Express it in Markdown, or
convert to PDF, where raw HTML is passed through.

### Word asks to update fields every time a document opens

That is the `--toc` field, and it is the price of a contents that stays correct
as the document is edited. Convert without `--toc` and no dialog appears.

### The PDF looks right but a code block is a dark box on a light page

The highlighting style is a dark one. Either use a light style, or accept that
every code block in the document becomes a dark panel — which is what Amethyst
does on purpose, since a light box beside a dark one is worse than either.

### Output goes missing when piping

If the document is on stdout, warnings and confirmations move to stderr — that
is by design. If you are redirecting stderr away, you are discarding the
warnings too.
