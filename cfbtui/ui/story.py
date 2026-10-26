"""ESPN story HTML to Rich text, with the standard library's parser.

ESPN's story bodies are a small subset of HTML: ``p``, ``br``, ``hr``, ``strong``, ``em``, ``a`` and ``img``, plus
placeholders such as ``<photo1>``, ``<video1>`` and ``<alsosee>`` that stand in for media the terminal cannot show.
Paragraphs and ``br`` become line breaks, ``strong`` is bold, ``em`` italic, ``hr`` a rule and a link only its text.
Images and unknown tags are dropped (their text, if any, stays). Nothing is fetched and nothing is written.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from rich.text import Text

RULE = "─" * 24
_SKIP = frozenset({"script", "style"})
_BOLD = frozenset({"strong", "b"})
_ITALIC = frozenset({"em", "i"})
_BLOCKS = frozenset({"p", "div", "blockquote", "h1", "h2", "h3", "h4", "li", "ul", "ol"})


class _Renderer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out = Text()
        self._gap = 0  # line breaks owed before the next text
        self._bold = 0
        self._italic = 0
        self._skip = 0

    def _emit(self, text: str, style: str = "") -> None:
        if self.out.plain and self._gap:
            self.out.append("\n" * self._gap)
        self._gap = 0
        self.out.append(text, style=style or None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "br":
            self._gap = min(self._gap + 1, 2)
        elif tag == "hr":
            self._gap = 2
            self._emit(RULE, "dim")
            self._gap = 2
        elif tag in _BLOCKS:
            self._gap = 2
        elif tag in _BOLD:
            self._bold += 1
        elif tag in _ITALIC:
            self._italic += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCKS:
            self._gap = 2
        elif tag in _BOLD:
            self._bold = max(0, self._bold - 1)
        elif tag in _ITALIC:
            self._italic = max(0, self._italic - 1)

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data)
        if not self.out.plain or self._gap or self.out.plain.endswith("\n"):
            text = text.lstrip()
        if not text:
            return
        style = " ".join(s for s, on in (("bold", self._bold), ("italic", self._italic)) if on)
        self._emit(text, style)


def render_story(html: str) -> Text:
    """The story as Rich text; empty when ``html`` has no readable text."""
    renderer = _Renderer()
    renderer.feed(html)
    renderer.close()
    renderer.out.rstrip()
    return renderer.out
