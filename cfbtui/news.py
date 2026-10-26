"""The news feed's state and poller. No Textual in it; the app runs :meth:`NewsFeed.run` in a worker.

Polling is slow and stops when nobody is at the computer. Presence is the scoreboard scheduler's own answer
(:meth:`~cfbtui.poll.PollScheduler.present`), asked once a second through :meth:`NewsFeed.observe_presence`:
while away the loop parks and sends no request, and the first second back wakes it for one poll at once.

**Reading.** A story body is fetched only when the user opens that story, one request each, never by the poller.
Bodies are kept in memory for the session (the last :data:`STORY_CACHE`), nothing is written to disk.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from cfbtui.espn.models import NewsItem
from cfbtui.poll import STALE_FACTOR, Freshness, FreshnessState, PollScheduler

NEWS_INTERVAL = 600.0  # present: every 10 minutes
NEWS_BACKOFF_MAX = 1800.0  # after failures the wait doubles up to 30 minutes
STORY_CACHE = 20


class NewsSource(Protocol):
    """What the feed needs from :class:`~cfbtui.espn.client.EspnClient`."""

    async def news(self, limit: int = ...) -> tuple[NewsItem, ...]: ...

    async def story(self, url: str) -> str: ...


class NewsFeed:
    def __init__(
        self,
        client: NewsSource,
        scheduler: PollScheduler,
        *,
        interval: float = NEWS_INTERVAL,
        backoff_max: float = NEWS_BACKOFF_MAX,
        clock: Callable[[], float] = time.monotonic,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.client = client
        self.scheduler = scheduler  # asked only whether someone is at the computer
        self.interval = interval
        self.backoff_max = backoff_max
        self.on_change = on_change
        self._clock = clock
        self.items: tuple[NewsItem, ...] = ()  # newest first
        self.polling = False
        self.polls = 0
        self._failures = 0
        self._last_error: Exception | None = None
        self._last_ok: float | None = None
        self._opened: set[str] = set()  # ids the user has opened; memory only
        self._stories: OrderedDict[str, str] = OrderedDict()
        self._away = False
        self._wake = asyncio.Event()
        self._stopped = False

    # --- state ------------------------------------------------------------------

    @property
    def unread_count(self) -> int:
        return sum(1 for item in self.items if item.id not in self._opened)

    def is_unread(self, item: NewsItem) -> bool:
        return item.id not in self._opened

    def mark_read(self, item: NewsItem) -> None:
        if item.id not in self._opened:
            self._opened.add(item.id)
            self._changed()

    def freshness(self) -> Freshness:
        age = None if self._last_ok is None else max(0.0, self._clock() - self._last_ok)
        stale_after = STALE_FACTOR * self.interval
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

    def next_delay(self) -> float:
        """Seconds to wait after a poll: the interval, doubled per consecutive failure up to the cap."""
        if not self._failures:
            return self.interval
        return min(self.backoff_max, self.interval * 2**self._failures)

    # --- polling ----------------------------------------------------------------

    async def poll_once(self) -> None:
        """Fetch the feed once. Never raises on a bad fetch; the last good list stays."""
        self.polling = True
        try:
            items = await self.client.news()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a parser bug must not kill the loop either
            self._failures += 1
            self._last_error = exc
        else:
            self._failures = 0
            self._last_error = None
            self._last_ok = self._clock()
            self.items = tuple(sorted(items, key=lambda i: i.published, reverse=True))
        finally:
            self.polling = False
        self.polls += 1
        self._changed()

    def observe_presence(self) -> None:
        """Once a second from the app. Coming back from away wakes the loop for a poll right now."""
        present = self.scheduler.present()
        if present and self._away:
            self._away = False
            self.refresh()
        elif not present:
            self._away = True

    async def run(self) -> None:
        """Poll while someone is here; park, with no requests, while they are away."""
        while not self._stopped:
            self._wake.clear()
            if self.scheduler.present():
                await self.poll_once()
                delay: float | None = self.next_delay()
            else:
                self._away = True
                delay = None  # parked until observe_presence sees them come back
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=delay)

    def refresh(self) -> None:
        """Poll now instead of waiting. Ignored mid-fetch, and while away (nothing is requested then)."""
        if not self.polling and self.scheduler.present():
            self._wake.set()

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()

    # --- reading ----------------------------------------------------------------

    async def read(self, item: NewsItem) -> str:
        """The story's HTML, for a story the user just opened: one request, then the session cache."""
        assert item.story_url is not None
        if (body := self._stories.get(item.id)) is not None:
            self._stories.move_to_end(item.id)
            return body
        body = await self.client.story(item.story_url)
        self._stories[item.id] = body
        while len(self._stories) > STORY_CACHE:
            self._stories.popitem(last=False)
        return body

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()
