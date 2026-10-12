"""Bottom status line: poll health first, then the context around it.

``format_status`` is a pure function of a :class:`StatusView` and the glyph
set, so tests do not need a running app. The app builds a new view once a
second and calls :meth:`StatusBar.show`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from textual.widgets import Static

from cfbtui import __version__
from cfbtui.poll import Freshness, FreshnessState, format_age
from cfbtui.ui.glyphs import Glyphs, get


@dataclass(frozen=True, slots=True)
class StatusView:
    freshness: Freshness = field(default_factory=Freshness)
    week: int | None = None
    group: str = ""
    live: int = 0
    total: int = 0
    next_in: float | None = None  # seconds to the next poll; None while fetching or unknown
    polling: bool = False
    glyph_set: str = ""


def format_status(view: StatusView, glyphs: Glyphs, now: datetime | None = None) -> str:
    f = view.freshness
    match f.state:
        case FreshnessState.LOADING:
            health = f"{glyphs.loading} loading"
        case FreshnessState.FRESH:
            health = f"{glyphs.fresh} updated {format_age(f.age)} ago"
        case FreshnessState.STALE:
            health = f"{glyphs.stale} STALE {format_age(f.age)} old"
        case FreshnessState.ERROR:
            age = "no data yet" if f.age is None else f"showing data {format_age(f.age)} old"
            health = f"{glyphs.error} ERROR {age}"
    parts = [health]
    if view.polling:
        parts.append(f"{glyphs.refresh} polling")
    elif view.next_in is not None:
        parts.append(f"next {format_age(view.next_in)}")
    if view.week is not None:
        parts.append(f"Week {view.week}{f' {view.group}' if view.group else ''}")
    elif view.group:
        parts.append(view.group)
    if view.total:
        parts.append(f"{view.live} live of {view.total}")
    if f.state is FreshnessState.ERROR and f.failures > 1:
        parts.append(f"{f.failures} failed polls")
    parts.append(f"v{__version__}")
    if view.glyph_set:
        parts.append(f"glyphs: {view.glyph_set}")
    if now is not None:
        parts.append(f"{now:%a %H:%M:%S}")
    return glyphs.sep.join(parts)


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text-muted;
    }
    StatusBar.fresh { color: $text-muted; }
    StatusBar.stale { color: $warning; }
    StatusBar.error { color: $error; text-style: bold; }
    """

    def __init__(self, glyphs: Glyphs | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.glyphs = glyphs or get()
        self.view = StatusView()
        self.text = ""

    def on_mount(self) -> None:
        self.show(self.view)

    def show(self, view: StatusView, glyphs: Glyphs | None = None, now: datetime | None = None) -> None:
        if glyphs is not None:
            self.glyphs = glyphs
        self.view = view
        self.text = format_status(view, self.glyphs, now or datetime.now().astimezone())
        for state in FreshnessState:
            self.set_class(view.freshness.state is state, state.value)
        self.update(self.text)
