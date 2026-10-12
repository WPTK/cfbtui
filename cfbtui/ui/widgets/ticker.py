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
from textual.widgets import RichLog

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
    ScoreKind,
    StatusChanged,
    Upset,
    UpsetWatch,
)
from cfbtui.ui.glyphs import Glyphs

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
    period = f"OT{s.period - 4}" if s.period > 5 else "OT" if s.period > 4 else f"Q{s.period}"
    return f"{period} {s.clock}" if s.period else ""


def _rank_tag(rank: int | None, abbreviation: str, glyphs: Glyphs) -> str:
    return f"{glyphs.rank}{rank} {abbreviation}" if rank is not None else abbreviation


def format_event(event: Event, glyphs: Glyphs, *, stamp: datetime | None = None) -> Text:
    """One ticker line. ``stamp`` is the local time the event arrived, shown as ``HH:MM``."""
    body = _body(event, glyphs)
    line = Text()
    if stamp is not None:
        line.append(f"{stamp:%H:%M} ", style="dim")
    line.append(body, style=STYLES.get(event.kind, ""))
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
            name = f"OT{period - 4}" if period > 5 else "OT" if period > 4 else f"Q{period}"
            return f"{glyphs.period} {name} {matchup(game, glyphs)}  {scores(game)}"
        case Halftime():
            return f"{glyphs.halftime} HALFTIME {matchup(game, glyphs)}  {scores(game)}"
        case GameFinal(winner=winner):
            ot = " (OT)" if game.status.is_overtime else ""
            return f"{glyphs.final} FINAL{ot} {scores(game)}" if winner else f"{glyphs.final} FINAL{ot} TIE {scores(game)}"
        case StatusChanged(before=before, after=after):
            return f"{glyphs.stale} {matchup(game, glyphs)}  {_pretty(before)} to {_pretty(after)}"
        case RedZone(team=team):
            who = team.abbreviation if team else "?"
            at = game.situation.possession_text if game.situation else None
            return f"{glyphs.red_zone} RED ZONE {who}{f' at {at}' if at else ''}  {scores(game)}"
        case UpsetWatch(underdog=u, favorite=f):
            return f"{glyphs.upset_watch} UPSET WATCH {_rank_tag(u.rank, u.abbreviation, glyphs)} leads {_rank_tag(f.rank, f.abbreviation, glyphs)}  {scores(game)}"
        case Upset(underdog=u, favorite=f):
            return f"{glyphs.upset} UPSET {_rank_tag(u.rank, u.abbreviation, glyphs)} beats {_rank_tag(f.rank, f.abbreviation, glyphs)}  {scores(game)}"
        case _:
            return f"{glyphs.score} {matchup(game, glyphs)}  {scores(game)}"


def _pretty(status_name: str) -> str:
    return status_name.removeprefix("STATUS_").replace("_", " ").title()


class Ticker(RichLog):
    DEFAULT_CSS = """
    Ticker {
        height: 8;
        border-top: solid $panel-lighten-2;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, glyphs: Glyphs, **kwargs) -> None:
        super().__init__(max_lines=CAP, wrap=True, markup=False, highlight=False, auto_scroll=True, **kwargs)
        self.glyphs = glyphs
        self._entries: deque[tuple[datetime, Event]] = deque(maxlen=CAP)
        self.border_title = "ticker"

    def add_events(self, events: Iterable[Event], *, stamp: datetime | None = None) -> None:
        stamp = stamp or datetime.now()
        for event in events:
            self._entries.append((stamp, event))
            self.write(format_event(event, self.glyphs, stamp=stamp))

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def set_glyphs(self, glyphs: Glyphs) -> None:
        """Redraw the whole log in another glyph set."""
        self.glyphs = glyphs
        self.clear()
        for stamp, event in self._entries:
            self.write(format_event(event, glyphs, stamp=stamp))
