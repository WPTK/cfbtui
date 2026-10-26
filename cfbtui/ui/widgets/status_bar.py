"""Bottom status line: poll health first, then the context around it.

``format_status`` is a pure function of a :class:`StatusView` and the glyph
set, so tests do not need a running app. The app builds a new view once a
second and calls :meth:`StatusBar.show`. Given a width, the line drops its
least important segments (clock, glyph set, version first) until it fits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from textual.widgets import Static

from cfbtui import __version__
from cfbtui.espn.periods import week_label
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
    away: bool = False  # the slow interval is in force because nobody has touched the computer lately
    glyph_set: str = ""
    errors: int = 0  # games whose latest diff raised
    view_note: str = ""  # the active filter, conference and layout, if not the defaults
    update_ready: str = ""  # the version downloaded and waiting to be installed when cfbtui quits
    news_unread: int = 0  # news stories not yet opened


# Drop order when the line is too wide: the highest number goes first, health (0) never.
P_HEALTH, P_UPDATE, P_FAILING, P_WEEK, P_LIVE, P_NEWS, P_NOTE, P_NEXT, P_VERSION, P_GLYPHS, P_CLOCK = range(11)


def fit_segments(parts: list[tuple[int, str]], sep: str, width: int | None) -> str:
    """Join ``(priority, text)`` segments in order, dropping the least important until the line fits ``width``."""
    parts = list(parts)
    while width is not None and len(parts) > 1 and len(sep.join(text for _, text in parts)) > width:
        # the highest priority number goes; of equals, the one furthest right
        drop = max(range(len(parts)), key=lambda i: (parts[i][0], i))
        del parts[drop]
    return sep.join(text for _, text in parts)


def format_status(view: StatusView, glyphs: Glyphs, now: datetime | None = None, width: int | None = None) -> str:
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
    parts = [(P_HEALTH, health)]
    if view.polling:
        parts.append((P_NEXT, f"{glyphs.refresh} polling"))
    elif view.next_in is not None:
        parts.append((P_NEXT, f"next {format_age(view.next_in)}{' (away)' if view.away else ''}"))
    if view.week is not None:
        parts.append((P_WEEK, f"{week_label(view.week)}{f' {view.group}' if view.group else ''}"))
    elif view.group:
        parts.append((P_WEEK, view.group))
    if view.view_note:
        parts.append((P_NOTE, view.view_note))
    if view.total:
        parts.append((P_LIVE, f"{view.live} live of {view.total}"))
    if view.news_unread:
        parts.append((P_NEWS, f"{view.news_unread} unread news"))
    if f.state is FreshnessState.ERROR and f.failures > 1:
        parts.append((P_FAILING, f"{f.failures} failed polls"))
    if view.errors:
        parts.append((P_FAILING, f"{glyphs.error} {view.errors} game{'s' if view.errors != 1 else ''} failing to diff"))
    if view.update_ready:
        parts.append((P_UPDATE, f"update {view.update_ready} ready"))
    parts.append((P_VERSION, f"v{__version__}"))
    if view.glyph_set:
        parts.append((P_GLYPHS, f"glyphs: {view.glyph_set}"))
    if now is not None:
        parts.append((P_CLOCK, f"{now:%a %H:%M:%S}"))
    return fit_segments(parts, glyphs.sep, width)


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
        self._now: datetime | None = None

    def on_mount(self) -> None:
        self.show(self.view)

    def show(self, view: StatusView, glyphs: Glyphs | None = None, now: datetime | None = None) -> None:
        if glyphs is not None:
            self.glyphs = glyphs
        self.view = view
        self._now = now or datetime.now().astimezone()
        self._refit()
        for state in FreshnessState:
            self.set_class(view.freshness.state is state, state.value)

    def on_resize(self) -> None:
        self._refit()

    def _refit(self) -> None:
        width = self.size.width - 2 if self.size.width else None  # minus the side padding; unsized yet means no limit
        self.text = format_status(self.view, self.glyphs, self._now, width)
        self.update(self.text)
