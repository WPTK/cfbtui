"""Typed events the :class:`~cfbtui.state.store.GameStore` emits when a poll changes a game.

Every event carries ``game``, the *after* state of the game that produced it.
Events are frozen dataclasses so the UI can pattern-match on the class and
trust the fields. ``str(event)`` gives a terse one-line description meant for
logs and the live spot check; widgets build their own text from the fields
and the glyph table.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cfbtui.espn.models import Competitor, Game


class ScoreKind(StrEnum):
    """Value is the stable id; ``label`` is the short tag for tickers and logs."""

    TOUCHDOWN = "touchdown"
    FIELD_GOAL = "field_goal"
    SAFETY = "safety"
    TWO_POINT = "two_point"
    PAT = "pat"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            "touchdown": "TD",
            "field_goal": "FG",
            "safety": "SAFETY",
            "two_point": "2PT",
            "pat": "PAT",
            "unknown": "SCORE",
        }[self.value]


@dataclass(frozen=True, slots=True)
class Event:
    """Base class. ``kind`` is a stable string for logs and filters."""

    game: Game

    kind = "event"

    @property
    def game_id(self) -> str:
        return self.game.id

    def _tag(self) -> str:
        return f"[{self.game.short_name}] {self.game.score_line}"

    def __str__(self) -> str:
        return f"{self.kind} {self._tag()}"


# --- status -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GameStarted(Event):
    """``pre`` became ``in``. On a first sighting of a live game this fires too."""

    kind = "game_started"

    def __str__(self) -> str:
        s = self.game.status
        return f"KICKOFF {self._tag()} ({s.short_detail or f'Q{s.period}'})"


@dataclass(frozen=True, slots=True)
class PeriodChanged(Event):
    period: int

    kind = "period_changed"

    @property
    def is_overtime(self) -> bool:
        return self.period > 4

    def __str__(self) -> str:
        name = f"OT{self.period - 4}" if self.is_overtime else f"Q{self.period}"
        return f"{name} {self._tag()}"


@dataclass(frozen=True, slots=True)
class Halftime(Event):
    kind = "halftime"

    def __str__(self) -> str:
        return f"HALFTIME {self._tag()}"


@dataclass(frozen=True, slots=True)
class GameFinal(Event):
    winner: Competitor | None
    loser: Competitor | None

    kind = "game_final"

    @property
    def is_tie(self) -> bool:
        return self.winner is None

    def __str__(self) -> str:
        ot = " (OT)" if self.game.status.is_overtime else ""
        return f"FINAL{ot} {self._tag()}"


@dataclass(frozen=True, slots=True)
class StatusChanged(Event):
    """Any other ``status.type.name`` transition (delay, postponement, cancellation)."""

    before: str
    after: str

    kind = "status_changed"

    def __str__(self) -> str:
        return f"STATUS {self._tag()} {self.before} -> {self.after}"


# --- scoring ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scored(Event):
    """One scoring play by ``team`` worth ``points``.

    ``inferred`` is True when the kind was guessed from the point delta rather
    than read from ESPN's ``lastPlay``; the UI may show those more quietly.
    ``text`` is ESPN's play description when known, else empty.
    """

    team: Competitor
    points: int
    score_kind: ScoreKind
    text: str = ""
    inferred: bool = False

    kind = "scored"

    @property
    def home_score(self) -> int:
        return self.game.home.score

    @property
    def away_score(self) -> int:
        return self.game.away.score

    def __str__(self) -> str:
        guess = "?" if self.inferred else ""
        s = self.game.status
        when = f" ({s.short_detail})" if s.short_detail else ""
        text = f" {self.text}" if self.text else ""
        return f"{self.score_kind.label}{guess} {self.team.abbreviation} +{self.points} {self._tag()}{when}{text}"


@dataclass(frozen=True, slots=True)
class ScoreCorrected(Event):
    """A team's score went *down*. ESPN does this when a play is overturned."""

    team: Competitor
    before: int
    after: int

    kind = "score_corrected"

    def __str__(self) -> str:
        return f"CORRECTION {self.team.abbreviation} {self.before} -> {self.after} {self._tag()}"


# --- situation --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RedZone(Event):
    """The team with possession is inside the opponent's 20."""

    team: Competitor | None

    kind = "red_zone"

    def __str__(self) -> str:
        who = self.team.abbreviation if self.team else "?"
        where = self.game.situation.possession_text if self.game.situation else None
        at = f" at {where}" if where else ""
        return f"RED ZONE {who}{at} {self._tag()}"


# --- upsets -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UpsetWatch(Event):
    """A live game where the lower-ranked (or unranked) side is leading."""

    underdog: Competitor
    favorite: Competitor

    kind = "upset_watch"

    def __str__(self) -> str:
        return f"UPSET WATCH {_rank_tag(self.underdog)} leads {_rank_tag(self.favorite)} {self._tag()}"


@dataclass(frozen=True, slots=True)
class Upset(Event):
    """The game is final and the underdog won."""

    underdog: Competitor
    favorite: Competitor

    kind = "upset"

    def __str__(self) -> str:
        return f"UPSET {_rank_tag(self.underdog)} over {_rank_tag(self.favorite)} {self._tag()}"


def _rank_tag(c: Competitor) -> str:
    return f"#{c.rank} {c.abbreviation}" if c.rank is not None else c.abbreviation
