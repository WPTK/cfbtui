"""Poll scheduler and the freshness model.

The scheduler is plain asyncio with no Textual in it. The app runs
:meth:`PollScheduler.run` in a worker and receives each :class:`PollResult`
through the ``on_result`` callback. Clocks and sleeping are injectable so the
timing paths are testable without waiting.

**What "stale" means.** :class:`Freshness` measures the age of the last
*successful fetch*, never the age of the last *change*. A long halftime, a
weather delay or a quiet idle morning produces polls that diff to nothing;
those polls are fresh. Data is only old when polls stop succeeding or stop
happening.

- ``loading``: nothing fetched yet and nothing has failed.
- ``fresh``: the last attempt worked and its age is within ``stale_after``.
- ``stale``: the last attempt worked but the age exceeds ``stale_after``. The
  scheduler itself fell behind (a sleeping laptop, a very slow fetch).
- ``error``: the last attempt failed. Cards stay on screen with the last good
  data; ``data_old`` says whether they should look old yet.

``stale_after`` is 2.5 poll intervals of whatever mode the scheduler is in, so
one missed poll does not flicker the display and two do.

**Intervals.** The fast interval runs while someone is at the computer, games
or no games; the slow one runs once the machine has seen no keyboard or mouse
input for ``away_after`` seconds (see :mod:`cfbtui.presence`). Focus does not
matter: the board may sit on a second monitor. A game that kicks off before
the next slow poll pulls that poll forward to its kickoff, and a user who
comes back gets a poll at once. After a failed poll the delay doubles per
consecutive failure up to a cap, and never drops below the normal interval.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from cfbtui import presence
from cfbtui.espn.client import GROUP_FBS
from cfbtui.espn.models import Ranking, Scoreboard
from cfbtui.state.events import Event
from cfbtui.state.store import GameStore

STALE_FACTOR = 2.5
RANKINGS_RETRY = 300.0


@dataclass(frozen=True, slots=True)
class PollIntervals:
    """Seconds. Defaults chosen with Bill on 2026-10-12."""

    live: float = 20.0  # while someone is at the computer
    idle: float = 120.0  # once they have walked away
    backoff_max: float = 120.0
    away_after: float = 300.0  # no keyboard or mouse input for this long means away


class FreshnessState(StrEnum):
    LOADING = "loading"
    FRESH = "fresh"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Freshness:
    state: FreshnessState = FreshnessState.LOADING
    age: float | None = None  # seconds since the last successful fetch
    stale_after: float = 0.0
    failures: int = 0
    error: str | None = None

    @property
    def data_old(self) -> bool:
        """True when what is on screen is old enough that cards should look it."""
        return self.age is not None and self.age > self.stale_after


def format_age(seconds: float | None) -> str:
    """``12s``, ``3m05s``, ``2h07m``. ``--`` when there is no age."""
    if seconds is None:
        return "--"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


@dataclass(frozen=True, slots=True)
class PollResult:
    """One poll attempt. ``scoreboard`` is ``None`` when the attempt failed."""

    freshness: Freshness
    scoreboard: Scoreboard | None = None
    events: tuple[Event, ...] = ()
    error: Exception | None = None
    generation: int = 0  # the scheduler's switch() count when this poll started

    @property
    def ok(self) -> bool:
        return self.error is None


class ScoreboardSource(Protocol):
    """What the scheduler needs from :class:`~cfbtui.espn.client.EspnClient`."""

    async def scoreboard(self, *, week: int | None = ..., group: int = ...) -> Scoreboard: ...

    async def rankings(self) -> tuple[Ranking, ...]: ...


class PollScheduler:
    def __init__(
        self,
        client: ScoreboardSource,
        store: GameStore | None = None,
        *,
        intervals: PollIntervals | None = None,
        week: int | None = None,
        group: int = GROUP_FBS,
        on_result: Callable[[PollResult], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        idle_for: Callable[[], float | None] | None = None,
    ) -> None:
        """``idle_for`` reports seconds since the user last touched the machine (``None`` means unknown);
        the default asks the machine itself."""
        self.client = client
        self.store = store if store is not None else GameStore()
        self.intervals = intervals if intervals is not None else PollIntervals()
        self.week = week
        self.group = group
        self.on_result = on_result
        self._clock = clock
        self._now = now
        self._idle_for = idle_for or presence.seconds_since_input

        self.scoreboard: Scoreboard | None = None
        self.polling = False
        self.away = False  # True while the slow interval is in force because nobody is at the computer
        self.polls = 0
        self._failures = 0
        self._last_error: Exception | None = None
        self._last_ok: float | None = None
        self._normal = self.intervals.live  # normal interval of the most recent schedule
        self._next_at: float | None = None
        self._rankings_loaded = False
        self._rankings_retry_at = 0.0
        self._wake = asyncio.Event()
        self._stopped = False
        self._generation = 0  # bumped by switch() so an in-flight fetch of the old week is dropped

    @property
    def generation(self) -> int:
        """Bumped by every :meth:`switch`. A result carrying an older number belongs to a view the user left."""
        return self._generation

    # --- timing -----------------------------------------------------------------

    def present(self) -> bool:
        """True unless the machine has gone ``away_after`` seconds without keyboard or mouse input."""
        idle = self._idle_for()
        return idle is None or idle < self.intervals.away_after

    def normal_delay(self) -> float:
        """Seconds to wait after a good poll: fast while someone is here, slow once they have left."""
        iv = self.intervals
        if self.present():
            return iv.live
        now = self._now()
        delay = iv.idle
        for game in self.store.games:
            if game.is_pregame:
                until = (game.date - now).total_seconds()
                if until > 0:
                    delay = min(delay, until)  # wake for the kickoff, then go back to sleep
        return delay

    def observe_presence(self) -> bool:
        """Once a second from the app. Someone coming back to the computer gets a poll right away.

        Returns True on the second they come back, so the app can wake other pollers too.
        """
        present = self.present()
        if present and self.away:
            self.away = False
            self.refresh()
            return True
        if not present:
            self.away = True
        return False

    def next_delay(self) -> float:
        """Seconds to wait before the next poll, including error backoff."""
        base = self.normal_delay()
        if self._failures and self._last_ok is None:
            base = min(base, self.intervals.live)  # nothing loaded yet: retry soon, not in two minutes
        if self._failures:
            return max(base, min(self.intervals.backoff_max, base * 2**self._failures))
        return base

    def seconds_until_next(self) -> float | None:
        """Countdown for the status bar; ``None`` while a fetch is in flight or before the first."""
        if self.polling or self._next_at is None:
            return None
        return max(0.0, self._next_at - self._clock())

    def freshness(self) -> Freshness:
        age = None if self._last_ok is None else max(0.0, self._clock() - self._last_ok)
        stale_after = STALE_FACTOR * self._normal
        if self._failures:
            state = FreshnessState.ERROR
        elif age is None:
            state = FreshnessState.LOADING
        elif age > stale_after:
            state = FreshnessState.STALE
        else:
            state = FreshnessState.FRESH
        error = None
        if self._last_error is not None and self._failures:
            error = f"{type(self._last_error).__name__}: {self._last_error}"
        return Freshness(state, age, stale_after, self._failures, error)

    # --- polling ----------------------------------------------------------------

    async def poll_once(self) -> PollResult:
        """Fetch, apply to the store, schedule the next poll, report. Never raises on a bad fetch."""
        self.polling = True
        generation = self._generation
        board: Scoreboard | None
        events: tuple[Event, ...]
        error: Exception | None
        try:
            await self._maybe_fetch_rankings()
            try:
                board = await self.client.scoreboard(week=self.week, group=self.group)
                if generation != self._generation:
                    # switch() ran mid-fetch; this board belongs to the old week.
                    board, events, error = None, (), None
                    return await self._finish(board, events, error, counted=False)
                events = tuple(self.store.apply_scoreboard(board))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a parser bug must not kill the poll loop either
                if generation != self._generation:
                    return await self._finish(None, (), None, counted=False)
                self._failures += 1
                self._last_error = exc
                board, events, error = None, (), exc
            else:
                self._failures = 0
                self._last_error = None
                self._last_ok = self._clock()
                self.scoreboard = board
                error = None
            self.polls += 1
        finally:
            self.polling = False
        return await self._finish(board, events, error)

    async def _finish(
        self,
        board: Scoreboard | None,
        events: tuple[Event, ...],
        error: Exception | None,
        *,
        counted: bool = True,
        generation: int | None = None,
    ) -> PollResult:
        generation = self._generation if generation is None else generation
        self.polling = False
        self.away = not self.present()
        self._normal = self.normal_delay()
        self._next_at = self._clock() + (self.next_delay() if counted else 0.0)
        result = PollResult(self.freshness(), board, events, error, generation)
        if counted and self.on_result is not None:
            self.on_result(result)
        return result

    async def _maybe_fetch_rankings(self) -> None:
        """Rankings feed the upset rule's fallback. Failing here never hurts freshness.

        Skipped while the scoreboard is failing, so a hanging ESPN costs one call, not two.
        """
        if self._rankings_loaded or self._failures or self._clock() < self._rankings_retry_at:
            return
        try:
            rankings = await self.client.rankings()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._rankings_retry_at = self._clock() + RANKINGS_RETRY
            return
        self.store.rule.set_rankings(rankings)
        self._rankings_loaded = True

    async def run(self) -> None:
        """Poll forever until :meth:`stop` or cancellation."""
        while not self._stopped:
            self._wake.clear()
            await self.poll_once()
            await self._wait(self.next_delay())

    async def _wait(self, delay: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=delay)

    def refresh(self) -> None:
        """Poll now instead of waiting. Ignored mid-fetch: that fetch is about to be fresh anyway."""
        if not self.polling:
            self._wake.set()

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()

    def switch(self, *, week: int | None, group: int | None = None) -> None:
        """Point at another week or group, forget the old games and poll right away."""
        self.week = week
        if group is not None:
            self.group = group
        self._generation += 1
        self.store.reset()
        self.scoreboard = None
        self._last_ok = None
        self._failures = 0
        self._last_error = None
        self._next_at = None
        self._wake.set()
