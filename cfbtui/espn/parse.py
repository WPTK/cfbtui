"""Tolerant parsers from raw ESPN JSON into :mod:`cfbtui.espn.models`.

ESPN's endpoints are unofficial, so nothing here raises on a missing or
wrongly typed key; absent data becomes a default. No I/O happens here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cfbtui.espn.models import (
    UNRANKED_SENTINELS,
    Competitor,
    Game,
    GameState,
    HomeAway,
    LastPlay,
    Odds,
    RankEntry,
    Ranking,
    Scoreboard,
    ScoringPlay,
    Situation,
    Status,
    Summary,
    Team,
)
from cfbtui.ui.theme import hex_color

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------- helpers


def _get(d: Any, *path: str | int, default: Any = None) -> Any:
    """Walk nested dicts/lists; return ``default`` if any step is missing or mistyped."""
    cur = d
    for step in path:
        if isinstance(step, int):
            if isinstance(cur, (list, tuple)) and -len(cur) <= step < len(cur):
                cur = cur[step]
            else:
                return default
        elif isinstance(cur, dict) and step in cur:
            cur = cur[step]
        else:
            return default
    return default if cur is None else cur


def _dicts(value: Any) -> list[dict]:
    """The dict items of ``value`` if it is a list, else an empty list."""
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, dict)]


def _str(value: Any, default: str = "") -> str:
    if value is None or isinstance(value, (dict, list)):
        return default
    return value if isinstance(value, str) else str(value)


def _opt_str(value: Any) -> str | None:
    text = _str(value)
    return text or None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _opt_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def parse_int(value: Any, default: int = 0) -> int:
    """``"27"``, ``27``, ``27.0`` -> 27; anything unparseable -> ``default``."""
    result = _opt_int(value)
    return default if result is None else result


def parse_rank(value: Any) -> int | None:
    """Poll rank, with ESPN's 0 and 99 sentinels (and junk) mapped to ``None``."""
    result = _opt_int(value)
    if result is None or result in UNRANKED_SENTINELS or result < 0:
        return None
    return result


def parse_date(value: str | None) -> datetime:
    """Parse ESPN's ``"2026-10-10T19:30Z"`` to a UTC-aware datetime; epoch on junk."""
    if not isinstance(value, str) or not value:
        return _EPOCH
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _EPOCH
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ----------------------------------------------------------------------- teams


def parse_team(raw: dict) -> Team:
    """Build a :class:`Team`; every field has a default."""
    raw = raw if isinstance(raw, dict) else {}
    abbreviation = _str(raw.get("abbreviation"))
    display = _str(raw.get("displayName")) or _str(raw.get("location")) or abbreviation
    short = _str(raw.get("shortDisplayName")) or _str(raw.get("location")) or abbreviation
    return Team(
        id=_str(raw.get("id")),
        abbreviation=abbreviation,
        display_name=display,
        short_name=short,
        color=hex_color(_opt_str(raw.get("color"))),
        alt_color=hex_color(_opt_str(raw.get("alternateColor"))),
        logo=_opt_str(raw.get("logo")),
        conference_id=_opt_str(raw.get("conferenceId")),
    )


def _overall_record(records: Any) -> str | None:
    """The season record only; home/road/conference splits are never a substitute."""
    for rec in _dicts(records):
        overall = _str(rec.get("name")).lower() == "overall" or _str(rec.get("type")).lower() == "total"
        if overall and rec.get("summary"):
            return _str(rec["summary"])
    return None


def parse_competitor(raw: dict) -> Competitor | None:
    """Build a :class:`Competitor`, or ``None`` if ``homeAway`` is not home/away."""
    if not isinstance(raw, dict):
        return None
    side = _str(raw.get("homeAway")).lower()
    if side not in ("home", "away"):
        return None
    home_away: HomeAway = "home" if side == "home" else "away"
    return Competitor(
        team=parse_team(_get(raw, "team", default={})),
        home_away=home_away,
        score=parse_int(raw.get("score")),
        rank=parse_rank(_get(raw, "curatedRank", "current")),
        record=_overall_record(raw.get("records")),
        winner=_opt_bool(raw.get("winner")),
    )


# ---------------------------------------------------------------------- status


_STATES = {s.value: s for s in GameState}


def parse_status(raw: dict | None) -> Status:
    """Build a :class:`Status`; unknown state defaults to ``PRE``."""
    if not isinstance(raw, dict):
        return Status()
    type_ = _get(raw, "type", default={})
    type_ = type_ if isinstance(type_, dict) else {}
    return Status(
        state=_STATES.get(_str(type_.get("state")).lower(), GameState.PRE),
        name=_str(type_.get("name")) or "STATUS_SCHEDULED",
        completed=type_.get("completed") is True,
        period=parse_int(raw.get("period")),
        clock=_str(raw.get("displayClock")) or "0:00",
        detail=_str(type_.get("detail")),
        short_detail=_str(type_.get("shortDetail")),
    )


def _parse_last_play(raw: Any) -> LastPlay | None:
    if not isinstance(raw, dict):
        return None
    return LastPlay(
        text=_str(raw.get("text")),
        type_text=_str(_get(raw, "type", "text")),
        type_id=_opt_str(_get(raw, "type", "id")),
        score_value=parse_int(raw.get("scoreValue")),
        team_id=_opt_str(_get(raw, "team", "id")),
    )


def parse_situation(raw: dict | None) -> Situation | None:
    """Build a live :class:`Situation`; ``None`` when ESPN sends none."""
    if not isinstance(raw, dict):
        return None
    return Situation(
        down=_opt_int(raw.get("down")),
        distance=_opt_int(raw.get("distance")),
        yard_line=_opt_int(raw.get("yardLine")),
        is_red_zone=raw.get("isRedZone") is True,
        possession=_opt_str(raw.get("possession")),
        home_timeouts=_opt_int(raw.get("homeTimeouts")),
        away_timeouts=_opt_int(raw.get("awayTimeouts")),
        down_distance_text=_opt_str(raw.get("downDistanceText")),
        possession_text=_opt_str(raw.get("possessionText")),
        last_play=_parse_last_play(raw.get("lastPlay")),
    )


def parse_odds(raw: list | dict | None) -> Odds | None:
    """Build :class:`Odds` from the first odds entry (list) or a single dict."""
    if isinstance(raw, (list, tuple)):
        items = _dicts(raw)
        raw = items[0] if items else None
    if not isinstance(raw, dict):
        return None
    return Odds(
        details=_opt_str(raw.get("details")),
        over_under=_opt_float(raw.get("overUnder")),
        spread=_opt_float(raw.get("spread")),
        provider=_opt_str(_get(raw, "provider", "name")),
    )


# ----------------------------------------------------------------------- games


def _broadcasts(raw: Any) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for entry in _dicts(raw):
        names = entry.get("names")
        if not isinstance(names, (list, tuple)):
            continue
        for name in names:
            if isinstance(name, str) and name:
                seen.setdefault(name, None)
    return tuple(seen)


def parse_event(event: dict) -> Game | None:
    """Build a :class:`Game`; ``None`` without an id or both home and away sides."""
    if not isinstance(event, dict):
        return None
    game_id = _opt_str(event.get("id"))
    if game_id is None:
        return None
    comp = _get(event, "competitions", 0, default={})
    if not isinstance(comp, dict):
        return None

    home: Competitor | None = None
    away: Competitor | None = None
    for raw in _dicts(comp.get("competitors")):
        parsed = parse_competitor(raw)
        if parsed is None:
            continue
        if parsed.home_away == "home" and home is None:
            home = parsed
        elif parsed.home_away == "away" and away is None:
            away = parsed
    if home is None or away is None:
        return None

    return Game(
        id=game_id,
        date=parse_date(_opt_str(event.get("date")) or _opt_str(comp.get("date"))),
        name=_str(event.get("name")),
        short_name=_str(event.get("shortName")),
        home=home,
        away=away,
        status=parse_status(comp.get("status") or event.get("status")),
        situation=parse_situation(comp.get("situation")),
        odds=parse_odds(comp.get("odds")),
        week=_opt_int(_get(event, "week", "number")),
        season_year=_opt_int(_get(event, "season", "year")),
        season_type=_opt_int(_get(event, "season", "type")),
        broadcasts=_broadcasts(comp.get("broadcasts")),
        conference_game=comp.get("conferenceCompetition") is True,
        neutral_site=comp.get("neutralSite") is True,
        venue=_opt_str(_get(comp, "venue", "fullName")),
        headline=_opt_str(_get(comp, "headlines", 0, "shortLinkText")),
    )


def parse_scoreboard(payload: dict) -> Scoreboard:
    """Build a :class:`Scoreboard`, skipping events that do not parse."""
    if not isinstance(payload, dict):
        return Scoreboard()
    games = tuple(g for g in map(parse_event, _dicts(payload.get("events"))) if g is not None)
    season_year = _opt_int(_get(payload, "leagues", 0, "season", "year"))
    if season_year is None:
        season_year = next((g.season_year for g in games if g.season_year is not None), None)
    week = _opt_int(_get(payload, "week", "number"))
    if week is None:
        week = next((g.week for g in games if g.week is not None), None)
    return Scoreboard(games=games, week=week, season_year=season_year)


# -------------------------------------------------------------------- rankings


def _opt_date(value: Any) -> datetime | None:
    """A date string as a UTC datetime; ``None`` when absent or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    parsed = parse_date(value)
    return None if parsed == _EPOCH else parsed


def parse_rank_entry(raw: dict) -> RankEntry | None:
    """Build a :class:`RankEntry`; ``None`` when there is no team id."""
    if not isinstance(raw, dict):
        return None
    team = _get(raw, "team", default={})
    team = team if isinstance(team, dict) else {}
    team_id = _opt_str(team.get("id"))
    if team_id is None:
        return None
    abbreviation = _str(team.get("abbreviation"))
    name = _str(team.get("location")) or _str(team.get("nickname")) or abbreviation
    return RankEntry(
        team_id=team_id,
        abbreviation=abbreviation,
        name=name,
        color=hex_color(_opt_str(team.get("color"))),
        rank=parse_rank(raw.get("current")),
        previous=parse_rank(raw.get("previous")),
        trend=_opt_str(raw.get("trend")),
        points=_opt_float(raw.get("points")),
        first_place_votes=parse_int(raw.get("firstPlaceVotes")),
        record=_opt_str(raw.get("recordSummary")),
    )


def _entries(raw: Any) -> tuple[RankEntry, ...]:
    return tuple(e for e in map(parse_rank_entry, _dicts(raw)) if e is not None)


def parse_rankings(payload: dict) -> tuple[Ranking, ...]:
    """Build every poll in a rankings payload."""
    if not isinstance(payload, dict):
        return ()
    polls: list[Ranking] = []
    for raw in _dicts(payload.get("rankings")):
        name = _str(raw.get("name"))
        polls.append(
            Ranking(
                id=_str(raw.get("id")),
                name=name,
                short_name=_str(raw.get("shortName")) or name,
                type=_str(raw.get("type")),
                week=_opt_int(_get(raw, "occurrence", "number")),
                season_year=_opt_int(_get(raw, "season", "year")),
                date=_opt_date(raw.get("date")),
                ranks=_entries(raw.get("ranks")),
                others=_entries(raw.get("others")),
                dropped_out=_entries(raw.get("droppedOut")),
            )
        )
    return tuple(polls)


# --------------------------------------------------------------------- summary


def _parse_scoring_play(raw: dict) -> ScoringPlay:
    return ScoringPlay(
        id=_str(raw.get("id")),
        period=parse_int(_get(raw, "period", "number")),
        clock=_str(_get(raw, "clock", "displayValue")) or "0:00",
        team_id=_str(_get(raw, "team", "id")),
        team_abbreviation=_str(_get(raw, "team", "abbreviation")),
        type_text=_str(_get(raw, "type", "text")),
        scoring_type=_str(_get(raw, "scoringType", "name")),
        text=_str(raw.get("text")),
        away_score=parse_int(raw.get("awayScore")),
        home_score=parse_int(raw.get("homeScore")),
    )


def parse_summary(payload: dict) -> Summary:
    """Build a :class:`Summary` from a game summary payload."""
    if not isinstance(payload, dict):
        return Summary(game_id="")
    probs = _dicts(payload.get("winprobability"))
    return Summary(
        game_id=_str(_get(payload, "header", "id")),
        scoring_plays=tuple(_parse_scoring_play(p) for p in _dicts(payload.get("scoringPlays"))),
        home_win_probability=_opt_float(probs[-1].get("homeWinPercentage")) if probs else None,
        status=parse_status(_get(payload, "header", "competitions", 0, "status")),
    )
