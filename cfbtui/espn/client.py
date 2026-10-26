"""Async client for ESPN's unofficial college football site API."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from cfbtui import __version__
from cfbtui.espn.periods import espn_request

if TYPE_CHECKING:
    from cfbtui.espn.models import NewsItem, Ranking, Scoreboard, Summary

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
GROUP_FBS = 80
GROUP_FCS = 81
NEWS_LIMIT = 30
STORY_HOST = "content.core.api.espn.com"
STORY_PATH = "/v1/sports/news/"

USER_AGENT = f"cfbtui/{__version__} (+https://github.com/WPTK/cfbtui)"


class EspnError(Exception):
    """Base class for every error raised by the client."""


class EspnHttpError(EspnError):
    """ESPN answered with a non-success HTTP status."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} from {url}")
        self.status_code = status_code
        self.url = url


class EspnNetworkError(EspnError):
    """The request failed before a usable response arrived (transport error, timeout, corrupt body, redirect loop)."""


class EspnSchemaError(EspnError):
    """ESPN answered, but nothing in the payload could be read (its format probably changed)."""


# Retrying cannot fix a corrupt body or a redirect loop.
_NOT_RETRIED = (httpx.DecodingError, httpx.TooManyRedirects)


class EspnClient:
    """Thin retrying wrapper over httpx for the endpoints cfbtui uses."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        retries: int = 3,
        backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> EspnClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying client, but only if this object created it."""
        if self._owns_client:
            await self._client.aclose()

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._get_url(f"{self._base_url}{path}", params)

    async def _get_url(self, url: str, params: dict[str, Any] | None = None) -> dict:
        last_error: EspnError | None = None
        for attempt in range(self._retries + 1):
            if attempt:
                await self._sleep(self._backoff * 2 ** (attempt - 1))
            try:
                response = await self._client.get(
                    url, params=params, headers={"User-Agent": USER_AGENT}, timeout=self._timeout
                )
            except httpx.RequestError as exc:
                error = EspnNetworkError(f"{type(exc).__name__} fetching {url}: {exc}")
                error.__cause__ = exc
                if isinstance(exc, _NOT_RETRIED):
                    raise error from exc
                last_error = error
                continue
            status = response.status_code
            if status >= 500 or status in (408, 429):
                last_error = EspnHttpError(status, str(response.url))
                continue
            if status >= 400:
                raise EspnHttpError(status, str(response.url))
            try:
                payload = response.json()
            except ValueError as exc:
                raise EspnError(f"Invalid JSON from {url}: {exc}") from exc
            if not isinstance(payload, dict):
                raise EspnError(f"Expected a JSON object from {url}")
            return payload
        assert last_error is not None
        raise last_error

    async def scoreboard_raw(
        self,
        *,
        week: int | None = None,
        date: str | datetime.date | None = None,
        group: int = GROUP_FBS,
        limit: int = 200,
        season_type: int | None = None,
    ) -> dict:
        if week is not None and date is not None:
            raise ValueError("pass either week or date, not both")
        params: dict[str, Any] = {"groups": group, "limit": limit}
        if week is not None:
            params["week"] = week
        if season_type is not None:
            params["seasontype"] = season_type
        if date is not None:
            if not isinstance(date, str):
                date = date.strftime("%Y%m%d")
            if len(date) != 8 or not date.isdigit():
                raise ValueError(f"date must be YYYYMMDD, got {date!r}")
            params["dates"] = date
        return await self._get_json("/scoreboard", params)

    async def rankings_raw(self) -> dict:
        return await self._get_json("/rankings")

    async def summary_raw(self, event_id: str) -> dict:
        return await self._get_json("/summary", {"event": event_id})

    async def news_raw(self, limit: int = NEWS_LIMIT) -> dict:
        return await self._get_json("/news", {"limit": limit})

    async def story_raw(self, url: str) -> dict:
        """One story's payload. ``url`` is a feed item's story API link; any other host or path is refused."""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != STORY_HOST or not parts.path.startswith(STORY_PATH):
            raise EspnError(f"Not a story link: {url}")
        return await self._get_url(f"https://{STORY_HOST}{parts.path}")

    async def scoreboard(
        self,
        *,
        week: int | None = None,
        date: str | datetime.date | None = None,
        group: int = GROUP_FBS,
        limit: int = 200,
    ) -> Scoreboard:
        from cfbtui.espn.parse import parse_scoreboard

        week, season_type = espn_request(week)
        raw = await self.scoreboard_raw(
            week=week, date=date, group=group, limit=limit, season_type=season_type
        )
        board = parse_scoreboard(raw)
        # A quiet day is `"events": []`. Events that all fail to parse, or an `events` key that vanished
        # from an otherwise populated payload, mean ESPN changed its format.
        events = raw.get("events")
        dropped = bool(events) and isinstance(events, list) and not board.games
        if dropped or ("events" not in raw and raw):
            raise EspnSchemaError("ESPN changed its scoreboard format; no games could be read")
        return board

    async def rankings(self) -> tuple[Ranking, ...]:
        from cfbtui.espn.parse import parse_rankings

        return parse_rankings(await self.rankings_raw())

    async def summary(self, event_id: str) -> Summary:
        from cfbtui.espn.parse import parse_summary

        return parse_summary(await self.summary_raw(event_id))

    async def news(self, limit: int = NEWS_LIMIT) -> tuple[NewsItem, ...]:
        from cfbtui.espn.parse import parse_news

        raw = await self.news_raw(limit)
        if not isinstance(raw.get("articles"), list):
            raise EspnSchemaError("ESPN changed its news format; no `articles` list")
        return parse_news(raw)

    async def story(self, url: str) -> str:
        """The HTML body of a story, or ``""`` when ESPN serves none."""
        from cfbtui.espn.parse import parse_story

        return parse_story(await self.story_raw(url))
