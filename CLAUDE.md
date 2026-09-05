# CLAUDE.md

Amethyst is a Python CLI that turns a Markdown file into a well-typeset PDF or
Word (DOCX) document — one file in, one styled document out:

```sh
amethyst convert notes.md -o notes.pdf
amethyst convert notes.md -f docx
```

The point is output that looks deliberately typeset rather than printed from a
browser: good defaults with no flags required, and a shared theme so the same
source reads as the same document in both formats.

## Commands

The venv is Python 3.13 with all dependencies installed:

```sh
.venv/bin/python
.venv/bin/amethyst          # the CLI itself, or: .venv/bin/python -m amethyst
```

`amethyst` is only on `PATH` in a shell with the venv activated, which a tool
call does not have. A bare `amethyst ...` there fails as "command not found",
which looks like a broken install and is not one.

No `DYLD_FALLBACK_LIBRARY_PATH` export is needed any more: the PDF renderer
puts Homebrew's lib directory on the loader path itself, just before it imports
WeasyPrint. Only import `weasyprint` directly — outside Amethyst's own code —
and you will still need it:

```sh
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
```

All four of these should be clean before a commit:

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format src/ tests/
.venv/bin/mypy src/amethyst
```

`uv.lock` is tracked, so run `uv lock` after touching `[project.dependencies]`.
`uv lock --check` tells you whether it has drifted.

## Looking at the output

The suite proves a PDF is well-formed, not that it looks right — the two
rendering defects found while building the PDF path were both invisible to it.
So look at the pages. There is no `pdftoppm` or `pypdfium2` here, and `sips`
converts only the first page of a PDF, so split it first:

```sh
.venv/bin/python -c "
from pypdf import PdfReader, PdfWriter
for i, page in enumerate(PdfReader('out.pdf').pages):
    w = PdfWriter(); w.add_page(page); w.write(f'page{i}.pdf')
"
for f in page*.pdf; do sips -s format png "$f" --out "${f%.pdf}.png"; done
```
