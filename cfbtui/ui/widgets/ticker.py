"""Ticker: a scrolling log of store events, newest at the bottom.

Lines are built by :func:`format_event` from event fields and the glyph
table, never from ``str(event)``. The ticker keeps the events themselves (up
to ``CAP``) so switching glyph sets can redraw the whole log.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import datetime

from rich.text import Text
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from cfbtui.espn.models import Game
from cfbtui.state.events import (
    Event,
    GameFinal,
    GameStarted,
    Halftime,
    PeriodChanged,
    RedZone,
    ScoreCorrected,
    Scored,
    StatusChanged,
    Upset,
    UpsetWatch,
)
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.labels import period_name, pretty_status

CAP = 200

# Style per event kind. Plain color names so the terminal theme still has a say.
STYLES: dict[str, str] = {
    "scored": "bold green",
    "score_corrected": "bold magenta",
    "game_started": "cyan",
    "period_changed": "dim",
    "halftime": "yellow",
    "game_final": "bold",
    "status_changed": "yellow",
    "red_zone": "bold red",
    "upset_watch": "bold yellow",
    "upset": "bold white on red",
}


def matchup(game: Game, glyphs: Glyphs) -> str:
    return f"{game.away.abbreviation} {glyphs.at} {game.home.abbreviation}"


def scores(game: Game) -> str:
    return f"{game.away.abbreviation} {game.away.score} - {game.home.abbreviation} {game.home.score}"


def _when(game: Game) -> str:
    s = game.status
    if s.is_halftime:
        return "half"
    return f"{period_name(s.period)} {s.clock}" if s.period else ""


def _rank_tag(rank: int | None, abbreviation: str, glyphs: Glyphs) -> str:
    return f"{glyphs.rank}{rank} {abbreviation}" if rank is not None else abbreviation


def involves(event: Event, favorites: frozenset[str]) -> bool:
    """True when either team in the event's game is a favorite."""
    return event.game.away.id in favorites or event.game.home.id in favorites


def format_event(
    event: Event,
    glyphs: Glyphs,
    *,
    stamp: datetime | None = None,
    favorites: frozenset[str] = frozenset(),
) -> Text:
    """One ticker line. ``stamp`` is the local time the event arrived, shown as ``HH:MM``.

    A favorite's event gets the favorite glyph and a reversed body, so it stands out in a busy log.
    """
    body = _body(event, glyphs)
    line = Text()
    if stamp is not None:
        line.append(f"{stamp:%H:%M} ", style="dim")
    style = STYLES.get(event.kind, "")
    if involves(event, favorites):
        line.append(f"{glyphs.favorite} ", style="bold yellow")
        style = f"{style} reverse".strip()
    line.append(body, style=style)
    return line


def _body(event: Event, glyphs: Glyphs) -> str:
    game = event.game
    match event:
        case Scored(team=team, points=points, score_kind=kind, text=text, inferred=inferred):
            guess = glyphs.inferred if inferred else ""
            detail = f"  {text}" if text and not inferred else ""
            tag = f"{glyphs.for_score_kind(kind)} {kind.label}{guess} {team.abbreviation} +{points}"
            return f"{tag}  {scores(game)}  {_when(game)}{detail}".rstrip()
        case ScoreCorrected(team=team, before=before, after=after):
            return f"{glyphs.correction} CORRECTION {team.abbreviation} {before} to {after}  {scores(game)}"
        case GameStarted():
            return f"{glyphs.kickoff} KICKOFF {matchup(game, glyphs)}  {scores(game)}  {_when(game)}".rstrip()
        case PeriodChanged(period=period):
            return f"{glyphs.period} {period_name(period)} {matchup(game, glyphs)}  {scores(game)}"
        case Halftime():
            return f"{glyphs.halftime} HALFTIME {matchup(game, glyphs)}  {scores(game)}"
        case GameFinal(winner=winner):
            ot = " (OT)" if game.status.is_overtime else ""
            tie = "" if winner else " TIE"
            return f"{glyphs.final} FINAL{ot}{tie} {scores(game)}"
        case StatusChanged(before=before, after=after):
            return f"{glyphs.stale} {matchup(game, glyphs)}  {pretty_status(before)} to {pretty_status(after)}"
        case RedZone(team=team):
            who = team.abbreviation if team else "?"
            at = game.situation.possession_text if game.situation else None
            return f"{glyphs.red_zone} RED ZONE {who}{f' at {at}' if at else ''}  {scores(game)}"
        case UpsetWatch(underdog=u, favorite=f):
            under, fav = _rank_tag(u.rank, u.abbreviation, glyphs), _rank_tag(f.rank, f.abbreviation, glyphs)
            return f"{glyphs.upset_watch} UPSET WATCH {under} leads {fav}  {scores(game)}"
        case Upset(underdog=u, favorite=f):
            under, fav = _rank_tag(u.rank, u.abbreviation, glyphs), _rank_tag(f.rank, f.abbreviation, glyphs)
            return f"{glyphs.upset} UPSET {under} beats {fav}  {scores(game)}"
        case _:
            return f"{glyphs.score} {matchup(game, glyphs)}  {scores(game)}"


class TickerLine(Static):
    """One event's line. Clicking it, or Enter while it has focus, asks the app to locate its game."""

    BINDINGS = [
        Binding("enter", "select", show=False),
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
    ]

    DEFAULT_CSS = """
    TickerLine { height: auto; }
    TickerLine:hover { background: $boost; }
    TickerLine:focus { background: $accent 30%; }
    """

    can_focus = True

    def __init__(self, event: Event, stamp: datetime, glyphs: Glyphs, favorites: frozenset[str]) -> None:
        self.text = format_event(event, glyphs, stamp=stamp, favorites=favorites)
        super().__init__(self.text, markup=False)
        self.event = event
        self.stamp = stamp

    def redraw(self, glyphs: Glyphs, favorites: frozenset[str]) -> None:
        self.text = format_event(self.event, glyphs, stamp=self.stamp, favorites=favorites)
        self.update(self.text)

    def on_click(self) -> None:
        self.focus()
        self.action_select()

    def action_select(self) -> None:
        self.post_message(Ticker.LineSelected(self.event.game_id, self.event))

    def action_move(self, step: int) -> None:
        lines = list(self.parent.children) if self.parent else []
        if self in lines:
            target = lines[max(0, min(len(lines) - 1, lines.index(self) + step))]
            target.focus()
            target.scroll_visible()


class Ticker(VerticalScroll):
    """The log: one :class:`TickerLine` per event (up to ``CAP``), newest at the bottom."""

    DEFAULT_CSS = """
    Ticker {
        height: 8;
        border-top: solid $panel-lighten-2;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }
    """

    class LineSelected(Message):
        """A line was clicked or chosen with Enter; the app locates ``game_id``."""

        def __init__(self, game_id: str, event: Event) -> None:
            super().__init__()
            self.game_id = game_id
            self.event = event

    def __init__(self, glyphs: Glyphs, favorites: frozenset[str] = frozenset(), **kwargs) -> None:
        super().__init__(**kwargs)
        self.glyphs = glyphs
        self.favorites = favorites
        self._lines: deque[TickerLine] = deque()
        self.border_title = "ticker"

    def on_mount(self) -> None:
        self.anchor()  # stay on the newest line until the user scrolls up

    @property
    def lines(self) -> list[TickerLine]:
        """The live lines, oldest first."""
        return list(self._lines)

    def add_events(self, events: Iterable[Event], *, stamp: datetime | None = None) -> None:
        stamp = stamp or datetime.now()
        new = [TickerLine(e, stamp, self.glyphs, self.favorites) for e in events]
        self._lines.extend(new)
        excess = [self._lines.popleft() for _ in range(max(0, len(self._lines) - CAP))]
        for line in excess:
            if line.is_attached:
                line.remove()
        self.mount_all([line for line in new if line not in excess])

    def clear_log(self) -> None:
        """Forget every line, for a week or group switch."""
        for line in self._lines:
            line.remove()
        self._lines.clear()

    def set_glyphs(self, glyphs: Glyphs) -> None:
        """Redraw the whole log in another glyph set."""
        self.glyphs = glyphs
        self._redraw()

    def set_favorites(self, favorites: frozenset[str]) -> None:
        """Redraw the whole log with another set of favorites highlighted."""
        self.favorites = favorites
        self._redraw()

    def _redraw(self) -> None:
        for line in self._lines:
            line.redraw(self.glyphs, self.favorites)
