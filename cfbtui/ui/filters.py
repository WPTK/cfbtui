"""Which games the board shows: a filter (all, Top 25, live, favorites) and an optional conference.

Pure functions of a game, so the app filters its store's games and hands the result to the grid.
Conference ids are ESPN's. A conference we have no name for is listed as "Conference <id>"
rather than dropped.
"""
from __future__ import annotations

from collections.abc import Iterable

from cfbtui.espn.models import Game

FILTERS = ("all", "top25", "live", "favorites")
FILTER_LABELS = {"all": "All games", "top25": "Top 25", "live": "Live", "favorites": "Favorites"}

CONFERENCES = {
    "1": "ACC",
    "4": "Big 12",
    "5": "Big Ten",
    "8": "SEC",
    "9": "Pac-12",
    "12": "Conference USA",
    "15": "MAC",
    "17": "Mountain West",
    "18": "Independents",
    "37": "Sun Belt",
    "151": "American",
    # FCS, as ESPN numbers them
    "20": "Big Sky",
    "21": "MVFC",
    "24": "MEAC",
    "25": "NEC",
    "27": "Patriot",
    "29": "Southern",
    "30": "Southland",
    "31": "SWAC",
    "32": "FCS Independents",
    "48": "CAA",
    "177": "UAC",
    "179": "OVC",
}


def next_filter(current: str) -> str:
    return FILTERS[(FILTERS.index(current) + 1) % len(FILTERS)] if current in FILTERS else FILTERS[0]


def conference_name(conference_id: str) -> str:
    return CONFERENCES.get(conference_id, f"Conference {conference_id}")


def in_conference(game: Game, conference_id: str) -> bool:
    return conference_id in (game.away.team.conference_id, game.home.team.conference_id)


def conferences_on(games: Iterable[Game]) -> list[tuple[str, str]]:
    """``(id, name)`` for every conference with a team in ``games``, named ones first, by name."""
    seen = {
        t.conference_id
        for g in games
        for t in (g.away.team, g.home.team)
        if t.conference_id
    }
    return sorted(((i, conference_name(i)) for i in seen), key=lambda p: (p[0] not in CONFERENCES, p[1]))


def keep(game: Game, mode: str, favorites: frozenset[str], conference_id: str | None) -> bool:
    if conference_id is not None and not in_conference(game, conference_id):
        return False
    match mode:
        case "top25":
            return game.away.rank is not None or game.home.rank is not None
        case "live":
            return game.is_live
        case "favorites":
            return game.away.id in favorites or game.home.id in favorites
    return True


def describe(mode: str, conference_id: str | None, layout: str) -> str:
    """The view note for the status bar; empty for the plain default view."""
    parts = []
    if mode != "all":
        parts.append(FILTER_LABELS.get(mode, mode))
    if conference_id is not None:
        parts.append(conference_name(conference_id))
    if layout == "list":
        parts.append("list")
    return " ".join(parts)
