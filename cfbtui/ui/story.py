"""ESPN story HTML to Markdown, with the standard library's parser.

ESPN's story bodies are a small subset of HTML: ``p``, ``br``, ``hr``, ``strong``, ``em``, ``a`` and ``img``, plus
placeholders such as ``<photo1>``, ``<video1>`` and ``<alsosee>`` that stand in for media the terminal cannot show.
The result is a Markdown string for Textual's ``Markdown`` widget: paragraphs, ``**bold**``, ``*italic*``, ``---`` for
``hr``, ``##`` headings, ``-`` list items and ``>`` quotes. A link keeps only its text; images, scripts and unknown tags
are dropped (their text, if any, stays). Every character of ESPN text that Markdown would read as syntax is escaped, so
the story can only ever be text, and the output is capped at ``MAX_CHARS``. Nothing is fetched and nothing is written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from markdown_it import MarkdownIt

from cfbtui.espn.parse import clean_text

MAX_CHARS = 100_000
_SKIP = frozenset({"script", "style"})
_BOLD = frozenset({"strong", "b"})
_ITALIC = frozenset({"em", "i"})
_BLOCKS = frozenset({"p", "div", "ul", "ol"})
_HEADINGS = {"h1": "## ", "h2": "## ", "h3": "### ", "h4": "### "}
_SYNTAX = re.compile(r"[\\`*_\[\]<>#~|&]")
_LINE_START = re.compile(r"^(?:([-+=])|(\d+)([.)]))")


def _escape(text: str, line_start: bool) -> str:
    text = _SYNTAX.sub(r"\\\g<0>", text)
    if line_start:  # "- x", "+ x", "=== " and "1. x" would open a list or heading underline
        text = _LINE_START.sub(lambda m: f"\\{m[1]}" if m[1] else f"{m[2]}\\{m[3]}", text)
    return text


def markdown_parser() -> MarkdownIt:
    """CommonMark with raw HTML, links, images and references switched off: a story is text, never a way out."""
    return MarkdownIt("commonmark").disable(["html_block", "html_inline", "link", "image", "autolink", "reference"])


@dataclass(frozen=True, slots=True)
class Story:
    markdown: str

    @property
    def plain(self) -> str:
        """The Markdown text; empty exactly when the story has no readable text."""
        return self.markdown


class _Renderer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, bool]] = []  # (markdown, is a list item)
        self._line = ""
        self._prefix = ""
        self._item = False
        self._quote = 0
        self._bold = 0
        self._italic = 0
        self._skip = 0
        self._size = 0

    def _flush(self) -> None:
        line = re.sub(r"(?:\\\n\s*)+$", "", self._line).strip()
        if line and self._size < MAX_CHARS:
            self._size += len(line)
            self.blocks.append((("> " * self._quote) + self._prefix + line, self._item))
        self._line = ""
        self._prefix = ""
        self._item = False

    def _block(self, prefix: str = "", item: bool = False) -> None:
        self._flush()
        self._prefix = prefix
        self._item = item

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "br" and self._line.strip() and not self._line.endswith("\n"):
            self._line += " " if self._prefix or self._quote else "\\\n"
        elif tag == "hr":
            self._block()
            self.blocks.append(("---", False))
        elif tag == "blockquote":
            self._block()
            self._quote += 1
        elif tag in _HEADINGS:
            self._block(_HEADINGS[tag])
        elif tag == "li":
            self._block("- ", True)
        elif tag in _BLOCKS:
            self._block()
        elif tag in _BOLD:
            self._bold += 1
        elif tag in _ITALIC:
            self._italic += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "blockquote":
            self._block()
            self._quote = max(0, self._quote - 1)
        elif tag in _HEADINGS or tag in _BLOCKS or tag == "li":
            self._block()
        elif tag in _BOLD:
            self._bold = max(0, self._bold - 1)
        elif tag in _ITALIC:
            self._italic = max(0, self._italic - 1)

    def handle_data(self, data: str) -> None:
        if self._skip or self._size >= MAX_CHARS:
            return
        text = re.sub(r"\s+", " ", clean_text(data))
        if not self._line or self._line.endswith("\n"):
            text = text.lstrip()
        core = text.strip()
        if not core:
            self._line += " " if text and self._line else ""
            return
        lead, trail = " " * (text[0] == " "), " " * (text[-1] == " ")
        mark = "*" * (2 * bool(self._bold) + bool(self._italic))
        start = not self._line.strip() or self._line.endswith("\n")
        self._line += f"{lead}{mark}{_escape(core, start)}{mark[::-1]}{trail}"


def render_story(html: str) -> Story:
    """The story as Markdown; empty when ``html`` has no readable text."""
    renderer = _Renderer()
    renderer.feed(html[: 4 * MAX_CHARS])
    renderer.close()
    renderer._flush()
    out = ""
    for index, (block, item) in enumerate(renderer.blocks):
        out += ("\n" if item and renderer.blocks[index - 1][1] else "\n\n" if out else "") + block
    return Story(out[:MAX_CHARS])
