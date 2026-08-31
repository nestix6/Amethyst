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

## Start here

**Read `.references/PLAN.md` at the start of every session.** It is the source
of truth: architecture, environment setup, verified findings, known gotchas,
and the phased build order. This file stays short on purpose — do not copy
detail into it.

`.references/` is gitignored and deliberately local-only, so it will be absent
from a fresh clone. It is removed, along with this section, before the repo
goes public.

## Commands

The venv is Python 3.13 with all dependencies installed:

```sh
.venv/bin/python
```

⚠️ **Anything that touches WeasyPrint needs this first**, or it fails with
`OSError: cannot load library 'libgobject-2.0-0'` — even though pango is
correctly installed. See PLAN.md §4.2.1.

```sh
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
```

## When the user asks to commit

Before committing, update `.references/PLAN.md` to match the actual state of
the project: tick off completed phases, record anything newly verified or
disproved, and correct any decision the implementation changed.
