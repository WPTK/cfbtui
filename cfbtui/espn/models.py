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
    def in_red_zone(self) -> bool:
        """Live with the offense inside the 20: the one definition the card, alerts and filter share."""
        return self.is_live and self.situation is not None and self.situation.is_red_zone

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
class TeamStat:
    """One boxscore line, as ESPN labels it (``display_value`` is e.g. ``"3-14"``)."""

    name: str
    label: str
    display_value: str


@dataclass(frozen=True, slots=True)
class TeamStats:
    team_id: str
    stats: tuple[TeamStat, ...] = ()


@dataclass(frozen=True, slots=True)
class GameLeader:
    category: str
    athlete: str
    stat_line: str
    team_id: str


@dataclass(frozen=True, slots=True)
class Drive:
    team_id: str
    team_abbreviation: str
    result: str
    plays: int
    yards: int
    time: str
    description: str
    in_progress: bool = False


@dataclass(frozen=True, slots=True)
class GameInfo:
    venue: str | None = None
    city: str | None = None
    state: str | None = None
    grass: bool | None = None
    attendance: int | None = None


@dataclass(frozen=True, slots=True)
class Summary:
    """The parts of a game summary payload worth keeping."""

    game_id: str
    scoring_plays: tuple[ScoringPlay, ...] = ()
    home_win_probability: float | None = None
    status: Status = field(default_factory=Status)
    team_stats: tuple[TeamStats, ...] = ()
    leaders: tuple[GameLeader, ...] = ()
    winprobability: tuple[float, ...] = ()
    drives: tuple[Drive, ...] = ()
    game_info: GameInfo | None = None
    odds: Odds | None = None
    broadcasts: tuple[str, ...] = ()
    away_linescores: tuple[int, ...] = ()
    home_linescores: tuple[int, ...] = ()
    recap_headline: str | None = None
    recap_description: str | None = None


# ------------------------------------------------------------------------ news


@dataclass(frozen=True, slots=True)
class NewsTeam:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class NewsItem:
    """One entry of ESPN's news feed. ``kind`` is ESPN's ``type`` (Story, Preview, HeadlineNews, Media)."""

    id: str
    kind: str
    headline: str
    description: str
    published: datetime
    premium: bool = False
    web_url: str | None = None
    story_url: str | None = None  # the story API link; only fetched when the user opens the story
    teams: tuple[NewsTeam, ...] = ()

    @property
    def is_video(self) -> bool:
        return self.kind.lower() == "media"

    @property
    def readable(self) -> bool:
        """True when ESPN's story API serves a body for it: not premium, not a video clip, and linked."""
        return not self.premium and not self.is_video and self.story_url is not None
