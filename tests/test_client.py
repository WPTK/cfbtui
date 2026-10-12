from __future__ import annotations

import datetime
import json
from pathlib import Path

import httpx
import pytest
import respx

from cfbtui import __version__
from cfbtui.espn.client import (
    BASE_URL,
    EspnClient,
    EspnError,
    EspnHttpError,
    EspnNetworkError,
)

FIXTURES = Path(__file__).parent / "fixtures"


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.fixture
def sleeper() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def mock():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


def make(sleeper: SleepRecorder, **kwargs) -> EspnClient:
    return EspnClient(sleep=sleeper, **kwargs)


async def test_scoreboard_week_params(mock, sleeper):
    route = mock.get("/scoreboard").respond(json={"events": []})
    async with make(sleeper) as client:
        assert await client.scoreboard_raw(week=7) == {"events": []}
    request = route.calls.last.request
    assert dict(request.url.params) == {"groups": "80", "week": "7", "limit": "200"}
    expected_agent = f"cfbtui/{__version__} (+https://github.com/WPTK/cfbtui)"
    assert request.headers["user-agent"] == expected_agent


@pytest.mark.parametrize("date", ["20261010", datetime.date(2026, 10, 10)])
async def test_scoreboard_date_params(mock, sleeper, date):
    route = mock.get("/scoreboard").respond(json={})
    async with make(sleeper) as client:
        await client.scoreboard_raw(date=date)
    params = dict(route.calls.last.request.url.params)
    assert params == {"groups": "80", "dates": "20261010", "limit": "200"}


async def test_week_and_date_conflict(mock, sleeper):
    async with make(sleeper) as client:
        with pytest.raises(ValueError):
            await client.scoreboard_raw(week=7, date="20261010")


async def test_fcs_group(mock, sleeper):
    route = mock.get("/scoreboard").respond(json={})
    async with make(sleeper) as client:
        await client.scoreboard_raw(group=81, limit=50)
    params = dict(route.calls.last.request.url.params)
    assert params["groups"] == "81"
    assert params["limit"] == "50"


async def test_rankings_raw(mock, sleeper):
    route = mock.get("/rankings").respond(json={"rankings": []})
    async with make(sleeper) as client:
        assert await client.rankings_raw() == {"rankings": []}
    assert route.call_count == 1
    assert not route.calls.last.request.url.params


async def test_summary_raw(mock, sleeper):
    route = mock.get("/summary").respond(json={"id": "x"})
    async with make(sleeper) as client:
        assert await client.summary_raw("401856717") == {"id": "x"}
    assert dict(route.calls.last.request.url.params) == {"event": "401856717"}


async def test_retry_5xx_then_success(mock, sleeper):
    route = mock.get("/rankings").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    async with make(sleeper) as client:
        assert await client.rankings_raw() == {"ok": True}
    assert route.call_count == 2
    assert sleeper.delays == [0.5]


async def test_retries_exhausted_5xx(mock, sleeper):
    route = mock.get("/rankings").respond(503)
    async with make(sleeper, retries=2) as client:
        with pytest.raises(EspnHttpError) as info:
            await client.rankings_raw()
    assert info.value.status_code == 503
    assert info.value.url.endswith("/rankings")
    assert route.call_count == 3
    assert sleeper.delays == [0.5, 1.0]


async def test_4xx_not_retried(mock, sleeper):
    route = mock.get("/summary").respond(404)
    async with make(sleeper) as client:
        with pytest.raises(EspnHttpError) as info:
            await client.summary_raw("1")
    assert info.value.status_code == 404
    assert route.call_count == 1
    assert sleeper.delays == []


async def test_network_error_exhausted(mock, sleeper):
    route = mock.get("/rankings").mock(side_effect=httpx.ConnectError("boom"))
    async with make(sleeper, retries=2) as client:
        with pytest.raises(EspnNetworkError) as info:
            await client.rankings_raw()
    assert isinstance(info.value.__cause__, httpx.ConnectError)
    assert route.call_count == 3


async def test_network_error_then_success(mock, sleeper):
    route = mock.get("/rankings").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": 1})]
    )
    async with make(sleeper) as client:
        assert await client.rankings_raw() == {"ok": 1}
    assert route.call_count == 2
    assert sleeper.delays == [0.5]


async def test_timeout_is_network_error(mock, sleeper):
    mock.get("/rankings").mock(side_effect=httpx.ReadTimeout("slow"))
    async with make(sleeper, retries=1) as client:
        with pytest.raises(EspnNetworkError):
            await client.rankings_raw()


async def test_non_json_body(mock, sleeper):
    route = mock.get("/rankings").respond(200, text="<html>nope</html>")
    async with make(sleeper) as client:
        with pytest.raises(EspnError):
            await client.rankings_raw()
    assert route.call_count == 1


async def test_parsed_scoreboard(mock, sleeper):
    pytest.importorskip("cfbtui.espn.parse")
    payload = json.loads((FIXTURES / "scoreboard_20261010_final.json").read_text("utf-8"))
    mock.get("/scoreboard").respond(json=payload)
    async with make(sleeper) as client:
        board = await client.scoreboard(date="20261010")
    assert len(board.games) == 46


async def test_context_manager_closes_owned_client():
    async with EspnClient() as client:
        inner = client._client
        assert not inner.is_closed
    assert inner.is_closed


async def test_context_manager_leaves_passed_client_open():
    async with httpx.AsyncClient() as http:
        async with EspnClient(client=http):
            pass
        assert not http.is_closed


async def test_timeout_applies_to_an_injected_client(mock, sleeper):
    route = mock.get("/rankings").respond(json={})
    injected = httpx.AsyncClient()
    try:
        async with make(sleeper, timeout=3.5, client=injected) as client:
            await client.rankings_raw()
    finally:
        await injected.aclose()
    assert route.calls.last.request.extensions["timeout"]["read"] == 3.5


async def test_iso_date_string_is_rejected(mock, sleeper):
    async with make(sleeper) as client:
        with pytest.raises(ValueError):
            await client.scoreboard_raw(date="2026-10-17")
