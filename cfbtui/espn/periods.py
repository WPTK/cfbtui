"""The calendar slots the scoreboard can show: regular-season weeks, then Bowls, then the Playoff.

ESPN files the postseason under season type 3: bowls are its week 1 and the College Football
Playoff is week 999. cfbtui folds all of that into one number line so week navigation, the
config file and ``--week`` stay a single integer: 1-15 are the regular weeks, 16 is Bowls and
17 is the Playoff.
"""
from __future__ import annotations

MIN_WEEK = 1
LAST_REGULAR_WEEK = 15
WEEK_BOWLS = 16
WEEK_PLAYOFF = 17
MAX_WEEK = WEEK_PLAYOFF

REGULAR_SEASON = 2
POSTSEASON = 3
_ESPN_BOWLS = 1
_ESPN_PLAYOFF = 999

NAMED = {"bowls": WEEK_BOWLS, "bowl": WEEK_BOWLS, "playoff": WEEK_PLAYOFF, "cfp": WEEK_PLAYOFF}


def week_label(week: int) -> str:
    """``Week 7``, ``Bowls`` or ``Playoff``."""
    if week == WEEK_BOWLS:
        return "Bowls"
    if week == WEEK_PLAYOFF:
        return "Playoff"
    return f"Week {week}"


def espn_request(week: int | None) -> tuple[int | None, int | None]:
    """``(week, seasontype)`` query values for ESPN; explicit weeks pin ``seasontype`` to the regular season."""
    if week == WEEK_BOWLS:
        return _ESPN_BOWLS, POSTSEASON
    if week == WEEK_PLAYOFF:
        return _ESPN_PLAYOFF, POSTSEASON
    return week, (REGULAR_SEASON if week is not None else None)


def from_espn(week: int | None, season_type: int | None) -> int | None:
    """The cfbtui week number for what ESPN calls ``week`` in ``season_type``."""
    if week is None or season_type != POSTSEASON:
        return week
    return WEEK_PLAYOFF if week == _ESPN_PLAYOFF else WEEK_BOWLS
