"""Test doubles shared by the poll and app tests."""
from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from cfbtui.espn.client import EspnNetworkError
from cfbtui.espn.models import Game, Ranking, Scoreboard, Summary
from cfbtui.espn.parse import parse_rankings, parse_scoreboard

FIXTURES = Path(__file__).parent / "fixtures"


def load_board(relative: str) -> Scoreboard:
    return parse_scoreboard(json.loads((FIXTURES / relative).read_text(encoding="utf-8")))


def load_game(relative: str) -> Game:
    board = load_board(relative)
    assert len(board.games) == 1, relative
    return board.games[0]


def load_rankings() -> tuple[Ranking, ...]:
    return parse_rankings(json.loads((FIXTURES / "rankings.json").read_text(encoding="utf-8")))


class FakeClient:
    """Plays back a script of scoreboards and errors, one per ``scoreboard()`` call.

    Items in the script are a :class:`Scoreboard` (returned), an exception
    (raised), or ``"hang"`` is not supported. The last item repeats when the
    script runs out, so a steady state needs one entry.
    """

    def __init__(self, *script: Scoreboard | Exception, rankings: tuple[Ranking, ...] | Exception = ()) -> None:
        self._script: deque[Scoreboard | Exception] = deque(script)
        self._last: Scoreboard | Exception | None = None
        self._rankings = rankings
        self.scoreboard_calls = 0
        self.rankings_calls = 0
        self.kwargs: list[dict] = []

    def push(self, *items: Scoreboard | Exception) -> None:
        self._script.extend(items)

    async def scoreboard(self, *, week: int | None = None, group: int = 80) -> Scoreboard:
        self.scoreboard_calls += 1
        self.kwargs.append({"week": week, "group": group})
        item = self._script.popleft() if self._script else self._last
        if item is None:
            raise EspnNetworkError("empty script")
        self._last = item
        if isinstance(item, Exception):
            raise item
        return item

    async def rankings(self) -> tuple[Ranking, ...]:
        self.rankings_calls += 1
        if isinstance(self._rankings, Exception):
            raise self._rankings
        return self._rankings

    async def summary(self, event_id: str) -> Summary:
        raise EspnNetworkError("FakeClient has no summaries")


class FakeClock:
    """A monotonic clock and a matching wall clock that only move when told to."""

    def __init__(self, start: datetime | None = None) -> None:
        self.t = 1000.0
        self.wall = start or datetime(2026, 10, 17, 15, 0, tzinfo=UTC)

    def __call__(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self.t += seconds
        self.wall += timedelta(seconds=seconds)
