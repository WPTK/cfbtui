"""DetailScreen: one game's scoring plays and win probability, from the ``summary`` endpoint.

The screen owns a small fetch loop beside the app's poll scheduler: one fetch
on open, then a refresh every ``live_refresh`` seconds until the game is final.
The loop is a worker of the screen, so popping the screen cancels it. The app
feeds in fresher scoreboard data with :meth:`DetailScreen.update_game`, so the
header keeps moving even between summary fetches.

Rendering is split out as pure functions of the game, the summary and a glyph
table (:func:`win_bar`, :func:`play_line`, :func:`build_detail`).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from cfbtui.espn.client import EspnError
from cfbtui.espn.models import Competitor, Game, ScoringPlay, Summary
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.labels import period_name, status_text

LIVE_REFRESH = 20.0
IDLE_REFRESH = 60.0
BAR_WIDTH = 30


class SummarySource(Protocol):
    async def summary(self, event_id: str) -> Summary: ...


def win_bar(home_probability: float | None, game: Game, glyphs: Glyphs, width: int = BAR_WIDTH) -> str | None:
    """``TEX 38% ░░░░░████████ 62% OU``; the home side fills from the right. ``None`` without a probability."""
    if home_probability is None:
        return None
    home = min(1.0, max(0.0, home_probability))
    filled = round(home * width)
    bar = glyphs.bar_empty * (width - filled) + glyphs.bar_full * filled
    away_pct = round((1 - home) * 100)
    home_pct = round(home * 100)
    return f"{game.away.abbreviation} {away_pct}% {bar} {home_pct}% {game.home.abbreviation}"


def _kind_icon(play: ScoringPlay, glyphs: Glyphs) -> str:
    key = f"{play.scoring_type} {play.type_text}".lower()
    if "touchdown" in key:
        return glyphs.touchdown
    if "field" in key:
        return glyphs.field_goal
    if "safety" in key:
        return glyphs.safety
    if "two" in key or "2-pt" in key or "2pt" in key:
        return glyphs.two_point
    if "extra" in key or "pat" in key:
        return glyphs.pat
    return glyphs.score


def play_line(play: ScoringPlay, game: Game, glyphs: Glyphs) -> str:
    """``Q1 6:56  ★ TEX  Cam Coleman 41 Yd pass ...  [TEX 7 - OU 0]``."""
    when = f"{period_name(play.period)} {play.clock}" if play.period else play.clock
    team = play.team_abbreviation or "?"
    score = f"{game.away.abbreviation} {play.away_score} - {game.home.abbreviation} {play.home_score}"
    text = f"  {play.text}" if play.text else ""
    return f"{when:<8} {_kind_icon(play, glyphs)} {team:<5}{text}  [{score}]".rstrip()


def header_lines(game: Game, glyphs: Glyphs) -> list[str]:
    def side(c: Competitor) -> str:
        rank = f"{glyphs.rank}{c.rank} " if c.rank is not None else ""
        record = f"  {c.record}" if c.record else ""
        score = "" if game.is_pregame else f"  {c.score}"
        return f"{rank}{c.team.display_name}{record}{score}"

    lines = [side(game.away), f"{glyphs.at} {side(game.home)}", status_text(game, glyphs, datetime.now(UTC))]
    if game.venue:
        lines.append(game.venue)
    return lines


def build_detail(game: Game, summary: Summary | None, glyphs: Glyphs, *, error: str | None = None) -> RenderableType:
    parts: list[RenderableType] = []
    head = Text()
    for i, line in enumerate(header_lines(game, glyphs)):
        head.append(line + "\n", style="bold" if i < 2 else "dim")
    parts.append(head)
    if summary is not None:
        bar = win_bar(summary.home_win_probability, game, glyphs)
        if bar:
            parts.append(Text(bar + "\n"))
    if error:
        parts.append(Text(f"{glyphs.error} Could not refresh ({error}). Trying again.\n", style="yellow"))
    if summary is None:
        if not error:
            parts.append(Text(f"{glyphs.loading} Loading scoring plays", style="dim"))
    elif not summary.scoring_plays:
        parts.append(Text("No scoring yet.", style="dim"))
    else:
        parts.append(Text("Scoring plays", style="bold underline"))
        body = Text()
        for play in summary.scoring_plays:
            body.append(play_line(play, game, glyphs) + "\n")
        parts.append(body)
    return Group(*parts)


class DetailScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
    ]

    DEFAULT_CSS = """
    DetailScreen { layout: vertical; }
    DetailScreen > VerticalScroll { height: 1fr; padding: 1 2; }
    """

    def __init__(
        self,
        client: SummarySource,
        game: Game,
        glyphs: Glyphs,
        *,
        live_refresh: float = LIVE_REFRESH,
        idle_refresh: float = IDLE_REFRESH,
    ) -> None:
        super().__init__()
        self.client = client
        self.game = game
        self.glyphs = glyphs
        self.live_refresh = live_refresh
        self.idle_refresh = idle_refresh
        self.summary: Summary | None = None
        self.error: str | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._paint()
        self.run_worker(self._loop(), name="detail", group="detail", exclusive=True)

    def _paint(self) -> None:
        self.query_one("#detail", Static).update(build_detail(self.game, self.summary, self.glyphs, error=self.error))

    def update_game(self, game: Game) -> None:
        """Fresher scoreboard data for this game, from the app's poll."""
        if game.id == self.game.id:
            self.game = game
            self._paint()

    def set_glyphs(self, glyphs: Glyphs) -> None:
        self.glyphs = glyphs
        self._paint()

    @property
    def done(self) -> bool:
        if self.game.is_final:
            return True
        return self.summary is not None and self.summary.status.completed

    async def _loop(self) -> None:
        while True:
            await self._fetch_once()
            if self.done:
                return
            await asyncio.sleep(self.live_refresh if self.game.is_live else self.idle_refresh)

    async def _fetch_once(self) -> None:
        try:
            summary = await self.client.summary(self.game.id)
        except EspnError as exc:
            self.error = str(exc) or type(exc).__name__
        except Exception as exc:  # a malformed payload must not kill the screen
            self.error = f"{type(exc).__name__}: {exc}"
        else:
            self.summary = summary
            self.error = None
        self._paint()

    def action_close(self) -> None:
        self.dismiss()
