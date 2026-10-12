"""Dataclass models for the slices of ESPN payloads cfbtui cares about.

Everything here is frozen and plain. Parsers in :mod:`cfbtui.espn.parse`
build these from raw JSON and absorb every missing key, so consumers can
rely on the shapes below without defensive ``get`` calls.

Conventions:

- Colors are normalised ``"#rrggbb"`` strings (see :func:`cfbtui.ui.theme.hex_color`).
- Ranks are ``int | None``; ``None`` means unranked. ESPN's 99 sentinel and
  the 0 used for "others receiving votes" both become ``None``.
- Dates are timezone-aware UTC ``datetime`` objects.
- Scores are ``int``; ESPN sends them as strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

HomeAway = Literal["home", "away"]

UNRANKED_SENTINELS = frozenset({0, 99})


class GameState(StrEnum):
    """``status.type.state`` as ESPN reports it."""

    PRE = "pre"
    IN = "in"
    POST = "post"


@dataclass(frozen=True, slots=True)
class Team:
    id: str
    abbreviation: str
    display_name: str
    short_name: str
    color: str
    alt_color: str
    logo: str | None = None
    conference_id: str | None = None


@dataclass(frozen=True, slots=True)
class Competitor:
    """One side of a game: the team plus its score, rank and record."""

    team: Team
    home_away: HomeAway
    score: int = 0
    rank: int | None = None
    record: str | None = None
    winner: bool | None = None

    @property
    def id(self) -> str:
        return self.team.id

    @property
    def abbreviation(self) -> str:
        return self.team.abbreviation

    @property
    def is_ranked(self) -> bool:
        return self.rank is not None


@dataclass(frozen=True, slots=True)
class Status:
    state: GameState = GameState.PRE
    name: str = "STATUS_SCHEDULED"
    completed: bool = False
    period: int = 0
    clock: str = "0:00"
    detail: str = ""
    short_detail: str = ""

    @property
    def is_halftime(self) -> bool:
        return self.name == "STATUS_HALFTIME"

    @property
    def is_overtime(self) -> bool:
        return self.period > 4


@dataclass(frozen=True, slots=True)
class LastPlay:
    text: str = ""
    type_text: str = ""
    type_id: str | None = None
    score_value: int = 0
    team_id: str | None = None


@dataclass(frozen=True, slots=True)
class Situation:
    """Live-game only. Absent for pregame and final games."""

    down: int | None = None
    distance: int | None = None
    yard_line: int | None = None
    is_red_zone: bool = False
    possession: str | None = None
    home_timeouts: int | None = None
    away_timeouts: int | None = None
    down_distance_text: str | None = None
    possession_text: str | None = None
    last_play: LastPlay | None = None


@dataclass(frozen=True, slots=True)
class Odds:
    details: str | None = None
    over_under: float | None = None
    spread: float | None = None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class Game:
    id: str
    date: datetime
    name: str
    short_name: str
    home: Competitor
    away: Competitor
    status: Status = field(default_factory=Status)
    situation: Situation | None = None
    odds: Odds | None = None
    week: int | None = None
    season_year: int | None = None
    season_type: int | None = None
    broadcasts: tuple[str, ...] = ()
    conference_game: bool = False
    neutral_site: bool = False
    venue: str | None = None
    headline: str | None = None

    @property
    def competitors(self) -> tuple[Competitor, Competitor]:
        return self.home, self.away

    def competitor(self, team_id: str | None) -> Competitor | None:
        if team_id is None:
            return None
        for c in self.competitors:
            if c.id == team_id:
                return c
        return None

    @property
    def state(self) -> GameState:
        return self.status.state

    @property
    def is_pregame(self) -> bool:
        return self.status.state == GameState.PRE

    @property
    def is_live(self) -> bool:
        return self.status.state == GameState.IN

    @property
    def is_final(self) -> bool:
        return self.status.state == GameState.POST and self.status.completed

    @property
    def is_tied(self) -> bool:
        return self.home.score == self.away.score

    @property
    def leader(self) -> Competitor | None:
        if self.is_tied:
            return None
        return self.home if self.home.score > self.away.score else self.away

    @property
    def trailer(self) -> Competitor | None:
        if self.is_tied:
            return None
        return self.away if self.home.score > self.away.score else self.home

    @property
    def margin(self) -> int:
        return abs(self.home.score - self.away.score)

    @property
    def score_line(self) -> str:
        """``"TEX 24 OU 27"``: away first, the way ESPN's shortName reads."""
        return f"{self.away.abbreviation} {self.away.score} {self.home.abbreviation} {self.home.score}"


@dataclass(frozen=True, slots=True)
class Scoreboard:
    games: tuple[Game, ...] = ()
    week: int | None = None
    season_year: int | None = None

    def get(self, game_id: str) -> Game | None:
        for g in self.games:
            if g.id == game_id:
                return g
        return None


@dataclass(frozen=True, slots=True)
class RankEntry:
    team_id: str
    abbreviation: str
    name: str
    color: str
    rank: int | None = None
    previous: int | None = None
    trend: str | None = None
    points: float | None = None
    first_place_votes: int = 0
    record: str | None = None


@dataclass(frozen=True, slots=True)
class Ranking:
    """One poll (AP, Coaches, FCS Coaches, D-II Coaches)."""

    id: str
    name: str
    short_name: str
    type: str
    week: int | None = None
    season_year: int | None = None
    date: datetime | None = None
    ranks: tuple[RankEntry, ...] = ()
    others: tuple[RankEntry, ...] = ()
    dropped_out: tuple[RankEntry, ...] = ()

    def rank_of(self, team_id: str) -> int | None:
        for entry in self.ranks:
            if entry.team_id == team_id:
                return entry.rank
        return None

    def entry_for(self, team_id: str) -> RankEntry | None:
        for entry in (*self.ranks, *self.others, *self.dropped_out):
            if entry.team_id == team_id:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class ScoringPlay:
    id: str
    period: int
    clock: str
    team_id: str
    team_abbreviation: str
    type_text: str
    scoring_type: str
    text: str
    away_score: int
    home_score: int


@dataclass(frozen=True, slots=True)
class Summary:
    """The parts of a game summary payload worth keeping."""

    game_id: str
    scoring_plays: tuple[ScoringPlay, ...] = ()
    home_win_probability: float | None = None
    status: Status = field(default_factory=Status)
