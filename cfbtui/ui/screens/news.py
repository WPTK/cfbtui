"""NewsScreen and StoryScreen: ESPN's college football headlines, and reading a story in the app.

The list comes from :class:`~cfbtui.news.NewsFeed`, which polls on its own slow clock and stops while the user
is away. A story's body is requested only when the user opens it. The footer line names ESPN and links the original.
"""
from __future__ import annotations

import os
import re
import sys
import webbrowser
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from cfbtui.espn.models import Game, NewsItem
from cfbtui.news import NewsFeed
from cfbtui.poll import Freshness, FreshnessState, format_age
from cfbtui.ui.filters import conference_name
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.story import render_story

MAX_CHIP_TEAMS = 6  # a story naming more teams is a roundup and gets no chips
KINDS = {"media": "video", "preview": "preview", "story": "story", "headlinenews": "story"}


def team_conferences(games: Iterable[Game]) -> dict[str, str]:
    """``team id -> conference id`` for every team on the board that has one. Bye teams are absent."""
    return {t.id: t.conference_id for g in games for t in (g.away.team, g.home.team) if t.conference_id}


def chips(item: NewsItem, conferences: dict[str, str]) -> tuple[list[str], list[str]]:
    """``(team names, conference names)`` to tag a story with; both empty for a roundup."""
    if len(item.teams) > MAX_CHIP_TEAMS:
        return [], []
    seen: dict[str, None] = {}
    for team in item.teams:
        if (conference := conferences.get(team.id)) is not None:
            seen.setdefault(conference_name(conference))
    return [t.name for t in item.teams], list(seen)


def age_label(published: datetime, now: datetime) -> str:
    seconds = max(0, int((now - published).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def kind_label(item: NewsItem) -> str:
    return KINDS.get(item.kind.lower(), item.kind.lower())


def health_line(f: Freshness, glyphs: Glyphs) -> str:
    """The freshness wording the status bar uses, for the news feed."""
    match f.state:
        case FreshnessState.LOADING:
            return f"{glyphs.loading} loading"
        case FreshnessState.FRESH:
            return f"{glyphs.fresh} updated {format_age(f.age)} ago"
        case FreshnessState.STALE:
            return f"{glyphs.stale} STALE {format_age(f.age)} old"
        case FreshnessState.ERROR:
            age = "no data yet" if f.age is None else f"showing news {format_age(f.age)} old"
            return f"{glyphs.error} ERROR {age}"


def is_espn_link(url: str | None) -> bool:
    if not url or re.search(r"[\\@\s\x00-\x1f\x7f]", url):  # browsers read these differently from urlsplit
        return False
    parts = urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme in ("http", "https") and (host == "espn.com" or host.endswith(".espn.com"))


def default_opener(url: str) -> bool:
    """Open ``url`` in the user's browser. False when there is none: a Linux session with no display would
    otherwise start a text browser on the terminal the app is drawing on."""
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return webbrowser.open(url)


def open_original(screen: Screen, item: NewsItem, opener: Callable[[str], object]) -> None:
    if item.web_url is None or not is_espn_link(item.web_url):
        screen.notify("No link to open for that story.", timeout=3)
        return
    try:
        opened = opener(item.web_url)
    except Exception as exc:  # no browser to launch is the user's setup, not a crash
        screen.notify(f"Could not open the browser: {exc}", severity="error", timeout=5)
        return
    if opened is False:
        screen.notify(f"No browser to open it in. The link: {item.web_url}", severity="warning", timeout=10)
        return
    screen.notify("Opened in your browser", timeout=2)


class NewsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("o", "open_original", "Open in browser"),
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    NewsScreen { layout: vertical; }
    NewsScreen #news-health { height: 1; padding: 0 2; color: $text-muted; }
    NewsScreen #news-health.stale { color: $warning; }
    NewsScreen #news-health.error { color: $error; text-style: bold; }
    NewsScreen OptionList { height: 1fr; border: none; padding: 0 1; }
    """

    def __init__(
        self,
        feed: NewsFeed,
        glyphs: Glyphs,
        conferences: Callable[[], dict[str, str]],
        *,
        opener: Callable[[str], object] = default_opener,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__()
        self.feed = feed
        self.glyphs = glyphs
        self.conferences = conferences
        self.opener = opener
        self._now = now
        self._shown: tuple[NewsItem, ...] = ()

    def compose(self) -> ComposeResult:
        yield Static("", id="news-health")
        yield OptionList(id="news-list")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_list()
        self.set_interval(1.0, self._show_health)

    def on_screen_resume(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        """Repaint from the feed, keeping the highlighted story."""
        lst = self.query_one(OptionList)
        current = self._current()
        conferences = self.conferences()
        now = self._now()
        self._shown = self.feed.items
        lst.clear_options()
        lst.add_options([Option(self._prompt(i, conferences, now), id=i.id) for i in self._shown])
        index = next((n for n, i in enumerate(self._shown) if current and i.id == current.id), None)
        lst.highlighted = index if index is not None else (0 if self._shown else None)
        self._show_health()

    def _prompt(self, item: NewsItem, conferences: dict[str, str], now: datetime) -> Text:
        unread = self.feed.is_unread(item)
        text = Text()
        text.append("NEW " if unread else "    ", style="bold yellow")
        text.append(f"{kind_label(item):<8}", style="dim")
        text.append(f"{age_label(item.published, now):>4}  ", style="dim")
        text.append(item.headline, style="bold" if unread else "")
        teams, confs = chips(item, conferences)
        if teams or confs:
            text.append("\n" + " " * 18)
            for name in teams:
                text.append(f"[{name}] ", style="cyan")
            for name in confs:
                text.append(f"[{name}] ", style="magenta")
        return text

    def _show_health(self) -> None:
        f = self.feed.freshness()
        line = health_line(f, self.glyphs)
        if f.state is FreshnessState.FRESH and not self.feed.items:
            line += "  -  no news"
        elif unread := self.feed.unread_count:
            line += f"  -  {unread} unread"
        health = self.query_one("#news-health", Static)
        health.update(line)
        for state in FreshnessState:
            health.set_class(f.state is state, state.value)

    def _current(self) -> NewsItem | None:
        index = self.query_one(OptionList).highlighted
        return self._shown[index] if index is not None and 0 <= index < len(self._shown) else None

    def on_option_list_option_selected(self, message: OptionList.OptionSelected) -> None:
        item = self._current()
        if item is not None:
            self.feed.mark_read(item)
            self.app.push_screen(StoryScreen(self.feed, item, self.glyphs, opener=self.opener))

    def action_open_original(self) -> None:
        item = self._current()
        if item is not None:
            open_original(self, item, self.opener)
            self.feed.mark_read(item)

    def action_refresh(self) -> None:
        self.feed.refresh()

    def action_close(self) -> None:
        self.dismiss()


class StoryScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("o,O", "open_original", "Open original"),
    ]

    DEFAULT_CSS = """
    StoryScreen { layout: vertical; }
    StoryScreen > VerticalScroll { height: 1fr; padding: 1 2; }
    StoryScreen #story-title { text-style: bold; margin-bottom: 1; }
    StoryScreen #story-body { height: auto; }
    StoryScreen #story-footer { height: auto; padding: 0 2; color: $text-muted; }
    """

    def __init__(
        self,
        feed: NewsFeed,
        item: NewsItem,
        glyphs: Glyphs,
        *,
        opener: Callable[[str], object] = default_opener,
    ) -> None:
        super().__init__()
        self.feed = feed
        self.item = item
        self.glyphs = glyphs
        self.opener = opener
        self.loaded = False

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(Text(self.item.headline), id="story-title")
            yield Static("", id="story-body")
        yield Static(self._footer(), id="story-footer")
        yield Footer()

    def _footer(self) -> Text:
        text = Text("ESPN. Press O to open the original")
        if self.item.web_url:
            text.append(f"\n{self.item.web_url}")
        return text

    def on_mount(self) -> None:
        body = self.query_one("#story-body", Static)
        if not self.item.readable:
            why = "a video clip" if self.item.is_video else "a premium story" if self.item.premium else "this story"
            body.update(self._summary(f"ESPN serves no text for {why}."))
            self.loaded = True
            return
        body.update(f"{self.glyphs.loading} Loading the story")
        self.run_worker(self._load(), name="story", group="story", exclusive=True)

    def _summary(self, note: str) -> Text:
        text = Text(self.item.description)
        if self.item.description:
            text.append("\n\n")
        text.append(note, style="dim")
        return text

    async def _load(self) -> None:
        body = self.query_one("#story-body", Static)
        try:
            html = await self.feed.read(self.item)
        except Exception as exc:  # an unreadable story must not take the screen down
            detail = str(exc) or type(exc).__name__
            body.update(self._summary(f"{self.glyphs.error} Could not load the story ({detail})."))
        else:
            story = render_story(html)
            body.update(story if story.plain else self._summary("ESPN served no text for this story."))
        self.loaded = True

    def action_open_original(self) -> None:
        open_original(self, self.item, self.opener)

    def action_close(self) -> None:
        self.dismiss()
