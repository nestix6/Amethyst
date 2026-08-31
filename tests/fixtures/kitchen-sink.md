---
title: The Amethyst Kitchen Sink
author: Patrik Repkovsky
date: 2026-08-31
subtitle: Every supported Markdown feature, in one document
keywords:
  - markdown
  - typesetting
---

# Kitchen sink

This document exercises every row of the feature support matrix. It is the
fixture the whole test suite converts, so a feature that renders badly here
gets noticed before it ships rather than after.

Paragraphs are separated by a blank line. A line ending in two spaces  
forces a hard break, and this sentence is the other side of one.

## Inline formatting

**Bold**, *italic*, ***bold italic***, ~~struck through~~ and `inline code`,
followed by a link to [the project](https://github.com/nestix6/Amethyst), a
bare autolink — https://example.com/autolinked — and an internal link back to
[the inline formatting section](#inline-formatting).

### Third level

#### Fourth level

##### Fifth level

###### Sixth level

Six heading levels exist so that PDF bookmarks, DOCX heading styles and the
`--toc-depth` cut-off all have something to be wrong about.

## Lists

- First item
- Second item, which is long enough to wrap when it is set in a real column
  width rather than a terminal
  - Nested item
  - Another nested item
    - Third level
- Third item

1. Ordered first
2. Ordered second
   1. Nested ordered
   2. And another
3. Ordered third

- [ ] An unchecked task
- [x] A completed task
- [ ] A task with `code` and **bold** in it

## Code

A fenced block with a language, which should be syntax highlighted:

```python
def convert(source: Path, fmt: Format) -> Path:
    """Turn one Markdown file into one typeset document."""
    document = load_document(source)
    if document.title is None:
        warn("no title; the document will have no running header")
    return render(document, fmt)
```

A fenced block with no language, which should not be:

```
$ amethyst convert notes.md -o notes.pdf
wrote notes.pdf (4 pages)
```

## Blockquotes

> A blockquote holds a paragraph, and keeps its own **inline formatting**.
>
> > A nested blockquote sits inside it.
>
> — attribution line

## Tables

| Feature      | PDF | DOCX | Notes                          |
| ------------ | :-: | :--: | ------------------------------ |
| Headings     | yes | yes  | mapped to Word's Heading 1–6   |
| Code blocks  | yes | yes  | shaded background in both      |
| Footnotes    | yes | part | endnote-style list in DOCX     |
| Right column |  1  |  2   | alignment is set by the colons |

## Horizontal rules

---

A rule sits above this paragraph and below it.

---

## Images

A local image, resolved relative to this file:

![The Amethyst mark](assets/amethyst.png)

<!-- Deliberately unreachable: this exercises the remote-image path and its
     failure handling. Nothing in the test suite requires it to resolve. -->

![A remote image](https://example.com/not-a-real-image.png)

## Definition lists

Theme
: A TOML file declaring fonts, a type scale, colours and page geometry.

Renderer
: The half of the pipeline that turns tokens into one output format.

## Footnotes

Footnotes are supported in the PDF pipeline properly[^pdf] and approximated in
the DOCX one[^docx].

[^pdf]: Rendered by WeasyPrint from CSS-styled markup.
[^docx]: Collected into an endnote-style list at the end of the document.

## Raw HTML

<div class="callout">
  A raw HTML block. The PDF pipeline passes it through; the DOCX pipeline
  skips it and warns, naming this line.
</div>

Raw <em>inline</em> HTML is handled the same way.
