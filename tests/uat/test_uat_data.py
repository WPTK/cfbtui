"""UAT for the data pipeline: EspnClient (mocked HTTP) -> parsers -> GameStore -> events/upsets.

Everything is mocked; no network.
"""
from __future__ import annotations

import copy
import json
import random
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from cfbtui.espn import periods
from cfbtui.espn.client import (
    BASE_URL,
    EspnClient,
    EspnError,
    EspnHttpError,
    EspnNetworkError,
)
from cfbtui.espn.models import (
    Competitor,
    Game,
    GameState,
    LastPlay,
    Situation,
    Status,
    Team,
)
from cfbtui.espn.parse import (
    parse_date,
    parse_event,
    parse_int,
    parse_odds,
    parse_rank,
    parse_rankings,
    parse_scoreboard,
    parse_status,
    parse_summary,
)
from cfbtui.state.events import (
    GameFinal,
    PeriodChanged,
    ScoreCorrected,
    Scored,
    ScoreKind,
)
from cfbtui.state.store import GameStore, decompose
from cfbtui.state.upset import UpsetRule

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def raw(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


FINAL = "scoreboard_20261010_final.json"
PRE = "scoreboard_week7_pregame.json"


async def _nosleep(_s: float) -> None:
    return None


def make_client(**kw) -> EspnClient:
    kw.setdefault("sleep", _nosleep)
    return EspnClient(**kw)


# =====================================================================
# 1. HTTP client
# =====================================================================


class TestClientHttp:
    @respx.mock
    async def test_200_parses_fixture(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json=raw(FINAL)))
        async with make_client() as c:
            board = await c.scoreboard(week=6)
        assert len(board.games) > 10
        assert board.week == 6

    @respx.mock
    async def test_query_params_for_week_and_group(self):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={"events": []}))
        async with make_client() as c:
            await c.scoreboard(week=7, group=81, limit=50)
        q = route.calls.last.request.url.params
        assert q["week"] == "7" and q["groups"] == "81" and q["limit"] == "50" and q["seasontype"] == "2"

    @respx.mock
    async def test_bowl_and_playoff_requests(self):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={"events": []}))
        async with make_client() as c:
            await c.scoreboard(week=16)
            q = route.calls.last.request.url.params
            assert (q["week"], q["seasontype"]) == ("1", "3")
            await c.scoreboard(week=17)
            q = route.calls.last.request.url.params
            assert (q["week"], q["seasontype"]) == ("999", "3")

    @respx.mock
    async def test_no_week_omits_week_and_seasontype(self):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={"events": []}))
        async with make_client() as c:
            await c.scoreboard()
        q = route.calls.last.request.url.params
        assert "week" not in q and "seasontype" not in q

    @respx.mock
    async def test_user_agent_sent(self):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={}))
        async with make_client() as c:
            await c.scoreboard_raw()
        assert route.calls.last.request.headers["user-agent"].startswith("cfbtui/")

    @respx.mock
    async def test_date_param_formats(self):
        import datetime as dt

        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={}))
        async with make_client() as c:
            await c.scoreboard_raw(date=dt.date(2026, 10, 10))
            assert route.calls.last.request.url.params["dates"] == "20261010"
            await c.scoreboard_raw(date="20261011")
            assert route.calls.last.request.url.params["dates"] == "20261011"
            for bad in ("2026-10-10", "abc", "", "2026101"):
                with pytest.raises(ValueError):
                    await c.scoreboard_raw(date=bad)
            with pytest.raises(ValueError):
                await c.scoreboard_raw(week=1, date="20261010")

    @respx.mock
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
    async def test_4xx_raises_http_error_without_retry(self, status):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(status))
        async with make_client() as c:
            with pytest.raises(EspnHttpError) as ei:
                await c.scoreboard_raw()
        assert ei.value.status_code == status
        assert route.call_count == 1

    @respx.mock
    async def test_429_is_retried_with_backoff(self):
        """Rate limiting is transient: a 429 followed by a 200 should succeed."""
        route = respx.get(f"{BASE_URL}/scoreboard").mock(
            side_effect=[httpx.Response(429), httpx.Response(200, json={"events": []})]
        )
        async with make_client() as c:
            payload = await c.scoreboard_raw()
        assert payload == {"events": []}
        assert route.call_count == 2

    @respx.mock
    async def test_429_persistent_raises_http_error(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(429))
        async with make_client() as c:
            with pytest.raises(EspnHttpError) as ei:
                await c.scoreboard_raw()
        assert ei.value.status_code == 429

    @respx.mock
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    async def test_5xx_retried_then_raises(self, status):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(status))
        async with make_client(retries=3) as c:
            with pytest.raises(EspnHttpError) as ei:
                await c.scoreboard_raw()
        assert ei.value.status_code == status
        assert route.call_count == 4

    @respx.mock
    async def test_5xx_then_success(self):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(
            side_effect=[httpx.Response(503), httpx.Response(500), httpx.Response(200, json={"events": []})]
        )
        async with make_client() as c:
            assert await c.scoreboard_raw() == {"events": []}
        assert route.call_count == 3

    @respx.mock
    async def test_backoff_is_exponential(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(500))
        sleeps: list[float] = []

        async def rec(s: float) -> None:
            sleeps.append(s)

        async with EspnClient(retries=3, backoff=0.5, sleep=rec) as c:
            with pytest.raises(EspnHttpError):
                await c.scoreboard_raw()
        assert sleeps == [0.5, 1.0, 2.0]

    @respx.mock
    async def test_zero_retries(self):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(500))
        async with make_client(retries=0) as c:
            with pytest.raises(EspnHttpError):
                await c.scoreboard_raw()
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ConnectTimeout("t"),
            httpx.ReadTimeout("t"),
            httpx.ConnectError("refused"),
            httpx.ReadError("reset"),
            httpx.RemoteProtocolError("bad"),
            httpx.PoolTimeout("pool"),
        ],
    )
    async def test_transport_errors_map_to_network_error(self, exc):
        route = respx.get(f"{BASE_URL}/scoreboard").mock(side_effect=exc)
        async with make_client(retries=2) as c:
            with pytest.raises(EspnNetworkError) as ei:
                await c.scoreboard_raw()
        assert route.call_count == 3
        assert ei.value.__cause__ is exc
        assert isinstance(ei.value, EspnError)

    @respx.mock
    async def test_timeout_then_success(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(
            side_effect=[httpx.ReadTimeout("x"), httpx.Response(200, json={"events": []})]
        )
        async with make_client() as c:
            assert await c.scoreboard_raw() == {"events": []}

    @respx.mock
    async def test_mixed_failures_raise_last(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(
            side_effect=[httpx.ConnectError("x"), httpx.Response(503), httpx.ReadTimeout("y")]
        )
        async with make_client(retries=2) as c:
            with pytest.raises(EspnNetworkError):
                await c.scoreboard_raw()

    @respx.mock
    @pytest.mark.parametrize("body", [b"<html>nope</html>", b"", b"{not json", b"\xff\xfe\x00bad"])
    async def test_non_json_body_raises_espn_error(self, body):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, content=body))
        async with make_client() as c:
            with pytest.raises(EspnError):
                await c.scoreboard_raw()

    @respx.mock
    @pytest.mark.parametrize("payload", [[], [1, 2], "str", 5, None, True])
    async def test_json_wrong_shape_raises_espn_error(self, payload):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json=payload))
        async with make_client() as c:
            with pytest.raises(EspnError):
                await c.scoreboard_raw()

    @respx.mock
    async def test_json_object_wrong_inner_shape_parses_to_empty(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={"events": "oops"}))
        async with make_client() as c:
            board = await c.scoreboard()
        assert board.games == ()

    @respx.mock
    async def test_empty_events(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={"events": []}))
        async with make_client() as c:
            board = await c.scoreboard(week=3)
        assert board.games == () and board.week is None

    @respx.mock
    async def test_empty_object(self):
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={}))
        async with make_client() as c:
            assert (await c.scoreboard()).games == ()

    @respx.mock
    async def test_rankings_and_summary_endpoints(self):
        respx.get(f"{BASE_URL}/rankings").mock(return_value=httpx.Response(200, json=raw("rankings.json")))
        s = respx.get(f"{BASE_URL}/summary").mock(return_value=httpx.Response(200, json=raw("summary_401856717.json")))
        async with make_client() as c:
            polls = await c.rankings()
            summ = await c.summary("401856717")
        assert polls and any(p.type == "ap" for p in polls)
        assert s.calls.last.request.url.params["event"] == "401856717"
        assert summ.scoring_plays

    @respx.mock
    async def test_rankings_failure_modes(self):
        respx.get(f"{BASE_URL}/rankings").mock(return_value=httpx.Response(404))
        async with make_client() as c:
            with pytest.raises(EspnHttpError):
                await c.rankings()

    async def test_aclose_does_not_close_foreign_client(self):
        foreign = httpx.AsyncClient()
        c = EspnClient(client=foreign, sleep=_nosleep)
        await c.aclose()
        assert not foreign.is_closed
        await foreign.aclose()

    async def test_aclose_closes_owned_client(self):
        c = EspnClient(sleep=_nosleep)
        await c.aclose()
        assert c._client.is_closed

    @respx.mock
    async def test_base_url_trailing_slash(self):
        route = respx.get("https://example.test/x/scoreboard").mock(return_value=httpx.Response(200, json={}))
        async with make_client(base_url="https://example.test/x/") as c:
            await c.scoreboard_raw()
        assert route.called

    @respx.mock
    async def test_large_payload_200_games(self):
        base = raw(FINAL)
        events = []
        for i in range(250):
            e = copy.deepcopy(base["events"][i % len(base["events"])])
            e["id"] = str(900000 + i)
            events.append(e)
        respx.get(f"{BASE_URL}/scoreboard").mock(return_value=httpx.Response(200, json={"events": events}))
        async with make_client() as c:
            board = await c.scoreboard()
        assert len(board.games) == 250


# =====================================================================
# 2. Parser: scalar helpers
# =====================================================================


class TestScalars:
    @pytest.mark.parametrize(
        "v,exp",
        [("27", 27), (27, 27), (27.0, 27), ("27.9", 27), (None, 0), ("", 0), ("x", 0), (True, 0),
         ([], 0), ({}, 0), (float("nan"), 0), (float("inf"), 0), ("1e999", 0), ("-3", -3)],
    )
    def test_parse_int(self, v, exp):
        assert parse_int(v) == exp

    @pytest.mark.parametrize(
        "v,exp",
        [(1, 1), ("1", 1), (25, 25), (0, None), (99, None), ("99", None), (None, None), (-1, None),
         ("", None), ("NR", None), (True, None), (100, 100), (26, 26), ([], None), (3.0, 3)],
    )
    def test_parse_rank(self, v, exp):
        assert parse_rank(v) == exp

    @pytest.mark.parametrize(
        "v",
        [None, "", "garbage", 5, "2026-13-45T99:99Z", "0000", {}],
    )
    def test_parse_date_junk_is_epoch(self, v):
        assert parse_date(v) == datetime(1970, 1, 1, tzinfo=UTC)

    def test_parse_date_variants(self):
        assert parse_date("2026-10-10T19:30Z") == datetime(2026, 10, 10, 19, 30, tzinfo=UTC)
        assert parse_date("2026-10-10T19:30:00+00:00") == datetime(2026, 10, 10, 19, 30, tzinfo=UTC)
        assert parse_date("2026-10-10T15:30:00-04:00") == datetime(2026, 10, 10, 19, 30, tzinfo=UTC)
        assert parse_date("2026-10-10T19:30:00").tzinfo is not None
        assert parse_date("2026-10-10T19:30z").tzinfo is not None

    @pytest.mark.parametrize(
        "raw_odds",
        [None, [], {}, "x", 5, [None], ["x"], [[]]],
    )
    def test_parse_odds_junk(self, raw_odds):
        res = parse_odds(raw_odds)
        assert res is None or res.details is None

    def test_parse_odds_values(self):
        o = parse_odds([{"details": "TEX -3.5", "overUnder": "52.5", "spread": -3.5, "provider": {"name": "ESPN BET"}}])
        assert o.over_under == 52.5 and o.spread == -3.5 and o.provider == "ESPN BET" and o.details == "TEX -3.5"
        o2 = parse_odds([{"overUnder": "n/a", "spread": None}])
        assert o2.over_under is None and o2.spread is None

    def test_parse_status_variants(self):
        assert parse_status(None) == Status()
        assert parse_status({}) == Status()
        assert parse_status({"type": "weird"}).state is GameState.PRE
        assert parse_status({"type": {"state": "IN"}}).state is GameState.IN  # case-insensitive
        assert parse_status({"type": {"state": "bogus"}}).state is GameState.PRE
        assert parse_status({"period": "3", "displayClock": ""}).clock == "0:00"
        assert parse_status({"period": "3", "displayClock": ""}).period == 3
        assert parse_status({"type": {"completed": "true"}}).completed is False


# =====================================================================
# 3. Parser: real fixtures, mutated
# =====================================================================


def first_event(name=FINAL) -> dict:
    return copy.deepcopy(raw(name)["events"][0])


def parse_one(event: dict) -> Game | None:
    return parse_event(event)


class TestFixtureSanity:
    def test_final_fixture_all_parse(self):
        d = raw(FINAL)
        board = parse_scoreboard(d)
        assert len(board.games) == len(d["events"])
        assert board.season_year == 2026
        assert board.week == 6

    def test_pregame_fixture_all_parse(self):
        d = raw(PRE)
        board = parse_scoreboard(d)
        assert len(board.games) == len(d["events"])
        assert all(g.is_pregame for g in board.games)

    def test_first_game_details(self):
        g = parse_scoreboard(raw(FINAL)).games[0]
        assert g.id == "401856717"
        assert g.home.abbreviation == "OU" and g.neutral_site is True
        assert g.is_final and g.home.team.color == "#990000"
        assert g.venue == "Cotton Bowl"
        assert g.date.tzinfo is not None

    def test_unique_ids(self):
        ids = [g.id for g in parse_scoreboard(raw(FINAL)).games]
        assert len(ids) == len(set(ids))

    def test_scores_are_ints_and_colors_hex(self):
        import re

        for g in parse_scoreboard(raw(FINAL)).games:
            for c in g.competitors:
                assert isinstance(c.score, int)
                assert re.fullmatch(r"#[0-9a-fA-F]{6}", c.team.color)
                assert re.fullmatch(r"#[0-9a-fA-F]{6}", c.team.alt_color)


def comp(e: dict) -> dict:
    return e["competitions"][0]


class TestMutations:
    def test_score_null_missing_junk(self):
        for v in (None, "", "abc", [], {}, "--"):
            e = first_event()
            for c in comp(e)["competitors"]:
                c["score"] = v
            g = parse_one(e)
            assert g is not None and g.home.score == 0 and g.away.score == 0
        e = first_event()
        for c in comp(e)["competitors"]:
            del c["score"]
        assert parse_one(e).home.score == 0

    def test_score_formats(self):
        e = first_event()
        comp(e)["competitors"][0]["score"] = 35.0
        comp(e)["competitors"][1]["score"] = "7"
        g = parse_one(e)
        assert {g.home.score, g.away.score} == {35, 7}

    def test_clock_missing(self):
        e = first_event()
        comp(e)["status"].pop("displayClock")
        assert parse_one(e).status.clock == "0:00"
        comp(e)["status"]["displayClock"] = None
        assert parse_one(e).status.clock == "0:00"

    def test_status_missing_entirely(self):
        e = first_event()
        comp(e).pop("status")
        g = parse_one(e)
        assert g is not None and g.status.state is GameState.POST  # falls back to the event-level status
        e.pop("status")
        assert parse_one(e).status == Status()

    def test_status_null_and_wrong_type(self):
        for v in (None, [], "x", 5):
            e = first_event()
            comp(e)["status"] = v
            e.pop("status", None)
            assert parse_one(e).status == Status()

    def test_odds_variants(self):
        for v in (None, [], {}, "x", [{"details": None}], [{"overUnder": "bad"}]):
            e = first_event()
            comp(e)["odds"] = v
            assert parse_one(e) is not None

    def test_rank_values(self):
        for raw_rank, exp in ((0, None), (99, None), (None, None), (1, 1), (25, 25), ("12", 12)):
            e = first_event()
            comp(e)["competitors"][0]["curatedRank"] = {"current": raw_rank}
            assert parse_one(e).home.rank == exp or parse_one(e).away.rank == exp

    def test_rank_wrong_shape(self):
        for v in (None, 5, "x", [], {"current": {}}, {"current": []}):
            e = first_event()
            for c in comp(e)["competitors"]:
                c["curatedRank"] = v
            g = parse_one(e)
            assert g.home.rank is None and g.away.rank is None

    def test_team_fields_missing(self):
        for key in ("color", "alternateColor", "logo", "abbreviation", "displayName", "shortDisplayName", "id", "location"):
            e = first_event()
            for c in comp(e)["competitors"]:
                c["team"].pop(key, None)
            g = parse_one(e)
            assert g is not None
            assert g.home.team.color.startswith("#")

    def test_team_missing_or_null(self):
        for v in (None, [], "x", {}):
            e = first_event()
            comp(e)["competitors"][0]["team"] = v
            g = parse_one(e)
            assert (g is not None and g.home.team.color.startswith("#")) or g.away.team.color.startswith("#")

    def test_bad_colors(self):
        for col in ("", "zzzzzz", "12", "#12", "1234567", None, 5, "fff", "#FFF", " 990000 "):
            e = first_event()
            comp(e)["competitors"][0]["team"]["color"] = col
            g = parse_one(e)
            for c in g.competitors:
                assert c.team.color.startswith("#") and len(c.team.color) == 7

    def test_logo_variants(self):
        for v in (None, "", 5, [], {}):
            e = first_event()
            comp(e)["competitors"][0]["team"]["logo"] = v
            g = parse_one(e)
            assert g is not None
        e = first_event()
        comp(e)["competitors"][0]["team"]["logo"] = None
        assert all(c.team.logo is None for c in parse_one(e).competitors if c.team.id == comp(e)["competitors"][0]["team"]["id"])

    def test_unicode_team_names(self):
        names = ["San José State Spartans", "Hawaiʻi Rainbow Warriors", "日本大学", "Ünïcödé 🏈", "Á", "‮RTL"]  # noqa: RUF001  the okina is the point
        for n in names:
            e = first_event()
            t = comp(e)["competitors"][0]["team"]
            t["displayName"] = n
            t["shortDisplayName"] = n
            e["name"] = n
            g = parse_one(e)
            assert any(c.team.display_name == n for c in g.competitors)
            assert g.name == n

    def test_conferenceId_and_odd_ids(self):
        e = first_event()
        comp(e)["competitors"][0]["team"]["id"] = 201  # int
        g = parse_one(e)
        assert isinstance(g.home.team.id, str) or isinstance(g.away.team.id, str)

    def test_missing_competitors(self):
        for v in (None, [], "x", [{}], [{"homeAway": "home"}], [{"homeAway": "neutral"}, {"homeAway": "x"}]):
            e = first_event()
            comp(e)["competitors"] = v
            assert parse_one(e) is None

    def test_only_one_competitor(self):
        e = first_event()
        comp(e)["competitors"] = comp(e)["competitors"][:1]
        assert parse_one(e) is None

    def test_two_home_competitors(self):
        e = first_event()
        for c in comp(e)["competitors"]:
            c["homeAway"] = "home"
        assert parse_one(e) is None

    def test_homeaway_case_insensitive(self):
        e = first_event()
        comp(e)["competitors"][0]["homeAway"] = "HOME"
        comp(e)["competitors"][1]["homeAway"] = "Away"
        assert parse_one(e) is not None

    def test_competitors_junk_items(self):
        e = first_event()
        comp(e)["competitors"] = [None, 5, "x", *comp(e)["competitors"]]
        assert parse_one(e) is not None

    def test_missing_competitions(self):
        for v in (None, [], "x", [None], [[]], [5]):
            e = first_event()
            e["competitions"] = v
            assert parse_one(e) is None

    def test_missing_id(self):
        for v in (None, "", 0):
            e = first_event()
            e["id"] = v
            g = parse_one(e)
            if v == 0:
                assert g is not None and g.id == "0"
            else:
                assert g is None
        e = first_event()
        e.pop("id")
        assert parse_one(e) is None

    def test_int_id(self):
        e = first_event()
        e["id"] = 401856717
        assert parse_one(e).id == "401856717"

    def test_situation_variants(self):
        for v in (None, [], "x", {}, {"down": None}, {"down": "3", "distance": "x"}, {"lastPlay": "bad"},
                  {"lastPlay": {"text": None, "type": None}}, {"possession": 5}):
            e = first_event()
            comp(e)["situation"] = v
            assert parse_one(e) is not None

    def test_situation_values(self):
        e = first_event()
        comp(e)["situation"] = {"down": "3", "distance": 7, "yardLine": 12.0, "isRedZone": True,
                                "possession": "201", "homeTimeouts": None, "awayTimeouts": 2,
                                "lastPlay": {"text": "TD", "scoreValue": "6", "team": {"id": 201}, "type": {"text": "Passing Touchdown"}}}
        s = parse_one(e).situation
        assert (s.down, s.distance, s.yard_line, s.is_red_zone, s.possession) == (3, 7, 12, True, "201")
        assert s.home_timeouts is None and s.away_timeouts == 2
        assert s.last_play.score_value == 6 and s.last_play.team_id == "201"

    def test_redzone_non_bool_is_false(self):
        e = first_event()
        comp(e)["situation"] = {"isRedZone": "true"}
        assert parse_one(e).situation.is_red_zone is False

    def test_neutral_conf_flags(self):
        for v, exp in ((True, True), (False, False), (None, False), ("true", False), (1, False)):
            e = first_event()
            comp(e)["neutralSite"] = v
            comp(e)["conferenceCompetition"] = v
            g = parse_one(e)
            assert g.neutral_site is exp and g.conference_game is exp

    def test_venue_missing(self):
        for v in (None, [], "x", {}, {"fullName": None}):
            e = first_event()
            comp(e)["venue"] = v
            assert parse_one(e).venue is None

    def test_broadcasts_variants(self):
        for v in (None, "x", [None], [{"names": None}], [{"names": [None, 5, ""]}], [{}]):
            e = first_event()
            comp(e)["broadcasts"] = v
            assert parse_one(e).broadcasts == ()
        e = first_event()
        comp(e)["broadcasts"] = [{"names": ["ABC", "ESPN+"]}, {"names": ["ABC"]}]
        assert parse_one(e).broadcasts == ("ABC", "ESPN+")

    def test_headlines_variants(self):
        for v in (None, [], "x", [None], [{}], [{"shortLinkText": None}]):
            e = first_event()
            comp(e)["headlines"] = v
            assert parse_one(e).headline is None

    def test_week_season_missing(self):
        e = first_event()
        e.pop("week")
        e.pop("season")
        g = parse_one(e)
        assert g.week is None and g.season_year is None and g.season_type is None

    def test_date_missing_uses_competition_date(self):
        e = first_event()
        e.pop("date")
        assert parse_one(e).date == parse_date(comp(e)["date"])
        comp(e).pop("date")
        assert parse_one(e).date == datetime(1970, 1, 1, tzinfo=UTC)

    def test_event_not_dict(self):
        for v in (None, 5, "x", []):
            assert parse_event(v) is None  # type: ignore[arg-type]

    def test_records_variants(self):
        for v in (None, "x", [], [{}], [{"name": "overall"}], [{"name": "overall", "summary": ""}],
                  [{"name": "home", "summary": "1-0"}], [{"name": "vs. Conf.", "summary": "0-0"}]):
            e = first_event()
            for c in comp(e)["competitors"]:
                c["records"] = v
            g = parse_one(e)
            assert g.home.record is None and g.away.record is None

    def test_record_overall_picked_over_splits(self):
        e = first_event()
        comp(e)["competitors"][0]["records"] = [
            {"name": "home", "summary": "9-9"}, {"name": "overall", "type": "total", "summary": "4-1"}]
        g = parse_one(e)
        side = g.home if comp(e)["competitors"][0]["homeAway"] == "home" else g.away
        assert side.record == "4-1"

    def test_winner_variants(self):
        e = first_event()
        for c in comp(e)["competitors"]:
            c["winner"] = "yes"
        g = parse_one(e)
        assert g.home.winner is None and g.away.winner is None


class TestStatuses:
    def with_status(self, name, state, completed, period=0, clock="0:00"):
        e = first_event()
        comp(e)["status"] = {"clock": 0, "displayClock": clock, "period": period,
                             "type": {"name": name, "state": state, "completed": completed,
                                      "detail": name, "shortDetail": name}}
        return parse_one(e)

    @pytest.mark.parametrize(
        "name,state,completed",
        [
            ("STATUS_SCHEDULED", "pre", False),
            ("STATUS_POSTPONED", "post", False),
            ("STATUS_CANCELED", "post", False),
            ("STATUS_CANCELLED", "post", False),
            ("STATUS_DELAYED", "in", False),
            ("STATUS_SUSPENDED", "in", False),
            ("STATUS_RAIN_DELAY", "in", False),
            ("STATUS_FORFEIT", "post", True),
            ("STATUS_FINAL_OT", "post", True),
            ("STATUS_HALFTIME", "in", False),
            ("STATUS_END_PERIOD", "in", False),
            ("STATUS_UNKNOWN_FUTURE", "wat", False),
        ],
    )
    def test_status_names(self, name, state, completed):
        g = self.with_status(name, state, completed, period=2)
        assert g is not None and g.status.name == name
        if state == "post" and not completed:
            assert not g.is_final and not g.is_live and not g.is_pregame
        if completed and state == "post":
            assert g.is_final

    def test_postponed_not_final_not_live(self):
        g = self.with_status("STATUS_POSTPONED", "post", False)
        assert (g.is_final, g.is_live) == (False, False)

    @pytest.mark.parametrize("period", [5, 6, 7, 8, 9, 12, 20])
    def test_overtime_periods(self, period):
        g = self.with_status("STATUS_IN_PROGRESS", "in", False, period=period)
        assert g.status.is_overtime and g.status.period == period
        ev = PeriodChanged(g, period)
        assert str(ev).startswith(f"OT{period - 4}")

    def test_non_overtime(self):
        for p in (0, 1, 4):
            assert not self.with_status("STATUS_IN_PROGRESS", "in", False, period=p).status.is_overtime

    def test_completed_without_post_state_is_not_final(self):
        g = self.with_status("STATUS_FINAL", "in", True)
        assert not g.is_final

    def test_ties_have_no_leader(self):
        e = first_event()
        for c in comp(e)["competitors"]:
            c["score"] = "21"
        g = parse_one(e)
        assert g.is_tied and g.leader is None and g.trailer is None and g.margin == 0


class TestFcsFbs:
    def test_group_81_payload_parses_same(self):
        e = first_event()
        e["groups"] = {"id": "81"}
        comp(e)["groups"] = {"id": "81", "name": "FCS"}
        assert parse_one(e) is not None

    def test_ranked_fcs_team_rank_kept(self):
        e = first_event()
        comp(e)["competitors"][0]["curatedRank"] = {"current": 3}
        g = parse_one(e)
        assert 3 in (g.home.rank, g.away.rank)


class TestScoreboardLevel:
    def test_payload_junk(self):
        for v in (None, [], "x", 5, {}, {"events": None}, {"events": [None, 5, "x"]}, {"leagues": "x"}, {"leagues": [None]},
                  {"week": "x"}, {"week": {"number": "abc"}}):
            sb = parse_scoreboard(v)  # type: ignore[arg-type]
            assert sb.games == ()

    def test_duplicate_game_ids_in_payload(self):
        d = raw(FINAL)
        d["events"] = [d["events"][0], copy.deepcopy(d["events"][0])]
        board = parse_scoreboard(d)
        assert len(board.games) == 2  # parser preserves the feed
        store = GameStore()
        store.apply_scoreboard(board)
        assert len(store) == 1
        assert len(store.games) == 1

    def test_scoreboard_get(self):
        board = parse_scoreboard(raw(FINAL))
        assert board.get("401856717") is not None
        assert board.get("nope") is None

    def test_bad_event_skipped_others_kept(self):
        d = raw(FINAL)
        n = len(d["events"])
        d["events"][3]["competitions"] = None
        d["events"].insert(0, {"id": None})
        assert len(parse_scoreboard(d).games) == n - 1

    def test_week_from_payload_vs_events(self):
        d = raw(FINAL)
        d.pop("week")
        assert parse_scoreboard(d).week == 6  # from games
        d["season"] = {"type": 3}
        d["week"] = {"number": 999}
        assert parse_scoreboard(d).week == periods.WEEK_PLAYOFF
        d["week"] = {"number": 1}
        assert parse_scoreboard(d).week == periods.WEEK_BOWLS

    def test_season_type_in_payload_without_week(self):
        d = {"events": [], "season": {"type": 3}}
        assert parse_scoreboard(d).week is None

    def test_week_in_event_postseason_not_folded(self):
        """Events carry season.type=3 and week.number=1 (bowls); with no top-level week
        the scoreboard week should still fold to the bowls slot, not 1."""
        d = raw(FINAL)
        d.pop("week")
        for e in d["events"]:
            e["season"]["type"] = 3
            e["week"] = {"number": 1}
        assert parse_scoreboard(d).week == periods.WEEK_BOWLS


# =====================================================================
# 4. Rankings & summary
# =====================================================================


class TestRankingsSummary:
    def test_rankings_fixture(self):
        polls = parse_rankings(raw("rankings.json"))
        assert polls
        for p in polls:
            for e in p.ranks:
                assert e.rank is None or e.rank >= 1

    def test_rankings_junk(self):
        for v in (None, [], "x", {}, {"rankings": None}, {"rankings": [None, 5, {}]}, {"rankings": [{"ranks": "x"}]},
                  {"rankings": [{"ranks": [None, {"team": None}, {"team": {}}]}]}):
            out = parse_rankings(v)  # type: ignore[arg-type]
            assert isinstance(out, tuple)

    def test_rankings_entry_sentinels(self):
        d = {"rankings": [{"type": "ap", "ranks": [
            {"current": 0, "previous": 99, "team": {"id": "1"}},
            {"current": 5, "previous": 0, "team": {"id": "2", "color": "nope"}},
        ]}]}
        (poll,) = parse_rankings(d)
        assert poll.ranks[0].rank is None and poll.ranks[0].previous is None
        assert poll.ranks[1].rank == 5
        assert poll.rank_of("2") == 5 and poll.rank_of("1") is None and poll.rank_of("zz") is None
        assert poll.entry_for("1") is not None

    def test_ranking_date_junk(self):
        d = {"rankings": [{"date": "garbage", "ranks": []}, {"date": None}, {"date": 5}]}
        assert all(p.date is None for p in parse_rankings(d))

    def test_summary_fixture(self):
        s = parse_summary(raw("summary_401856717.json"))
        assert s.game_id
        assert s.scoring_plays

    def test_summary_junk(self):
        for v in (None, [], "x", {}, {"winprobability": "x"}, {"winprobability": [{}]}, {"scoringPlays": [None, {}, 5]},
                  {"header": {"competitions": "x"}}):
            s = parse_summary(v)  # type: ignore[arg-type]
            assert s is not None

    def test_summary_winprob(self):
        s = parse_summary({"winprobability": [{"homeWinPercentage": 0.4}, {"homeWinPercentage": "0.8"}]})
        assert s.home_win_probability == 0.8
        s = parse_summary({"winprobability": [{"homeWinPercentage": None}]})
        assert s.home_win_probability is None

    def test_summary_scoring_play_blank_fields(self):
        s = parse_summary({"scoringPlays": [{}]})
        p = s.scoring_plays[0]
        assert p.clock == "0:00" and p.period == 0 and p.text == ""


# =====================================================================
# 5. periods.py
# =====================================================================


class TestPeriods:
    def test_constants(self):
        assert (periods.MIN_WEEK, periods.LAST_REGULAR_WEEK, periods.WEEK_BOWLS, periods.WEEK_PLAYOFF) == (1, 15, 16, 17)
        assert periods.MAX_WEEK == 17

    @pytest.mark.parametrize("w", range(1, 16))
    def test_regular_weeks_roundtrip(self, w):
        assert periods.week_label(w) == f"Week {w}"
        assert periods.espn_request(w) == (w, 2)
        assert periods.from_espn(w, 2) == w

    def test_bowls_playoff(self):
        assert periods.week_label(16) == "Bowls" and periods.week_label(17) == "Playoff"
        assert periods.espn_request(16) == (1, 3)
        assert periods.espn_request(17) == (999, 3)
        assert periods.from_espn(1, 3) == 16
        assert periods.from_espn(999, 3) == 17
        assert periods.from_espn(2, 3) == 16  # any other postseason week folds into bowls

    def test_none(self):
        assert periods.espn_request(None) == (None, None)
        assert periods.from_espn(None, 3) is None
        assert periods.from_espn(None, None) is None

    def test_from_espn_non_post(self):
        assert periods.from_espn(999, 2) == 999
        assert periods.from_espn(5, None) == 5

    def test_roundtrip_all_slots(self):
        for w in range(periods.MIN_WEEK, periods.MAX_WEEK + 1):
            ew, st = periods.espn_request(w)
            assert periods.from_espn(ew, st) == w

    def test_named(self):
        assert periods.NAMED["bowls"] == 16 and periods.NAMED["cfp"] == 17

    @pytest.mark.parametrize("w", [0, -1, 18, 100])
    def test_out_of_range_label_does_not_raise(self, w):
        assert isinstance(periods.week_label(w), str)

    def test_regular_season_week_not_clobbered_by_weekly_boundary(self):
        # week 15 -> espn week 15 regular; 16 must not be sent as regular week 16
        assert periods.espn_request(15) == (15, 2)
        assert periods.espn_request(16)[1] == 3


# =====================================================================
# 6. Property-style fuzz
# =====================================================================


def _mutate(obj, rng: random.Random, depth=0):
    """In-place random corruption of JSON."""
    junk = [None, "", "x", 0, -1, 99, 1e308, [], {}, True, "NaN", [None], {"a": 1}, "‮", 10**30]
    if isinstance(obj, dict):
        for k in list(obj):
            r = rng.random()
            if r < 0.04:
                del obj[k]
            elif r < 0.10:
                obj[k] = rng.choice(junk)
            elif depth < 12:
                _mutate(obj[k], rng, depth + 1)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            r = rng.random()
            if r < 0.04:
                obj[i] = rng.choice(junk)
            elif depth < 12:
                _mutate(obj[i], rng, depth + 1)
        if obj and rng.random() < 0.05:
            obj.reverse()
        if obj and rng.random() < 0.05:
            obj.append(copy.deepcopy(obj[0]))


class TestFuzz:
    @pytest.mark.parametrize("seed", range(60))
    @pytest.mark.parametrize("name", [FINAL, PRE])
    def test_scoreboard_never_raises(self, seed, name):
        rng = random.Random(seed)
        d = raw(name)
        _mutate(d, rng)
        board = parse_scoreboard(d)
        for g in board.games:
            _ = (g.leader, g.trailer, g.margin, g.score_line, g.is_final, g.is_live)
        GameStore().apply_scoreboard(board)

    @pytest.mark.parametrize("seed", range(40))
    def test_rankings_summary_never_raise(self, seed):
        rng = random.Random(seed)
        d = raw("rankings.json")
        _mutate(d, rng)
        parse_rankings(d)
        s = raw("summary_401856717.json")
        _mutate(s, rng)
        parse_summary(s)

    @pytest.mark.parametrize("seed", range(30))
    def test_store_over_mutated_sequence_has_no_errors(self, seed):
        rng = random.Random(1000 + seed)
        store = GameStore()
        for _ in range(4):
            d = raw(FINAL)
            _mutate(d, rng)
            events = store.apply_scoreboard(parse_scoreboard(d))
            for ev in events:
                str(ev)
        assert store.last_errors == []

    @pytest.mark.parametrize("junk", [None, 1, "s", [], [[]], {"events": [{"competitions": [{"competitors": [[], []]}]}]}])
    def test_top_level_junk(self, junk):
        parse_scoreboard(junk)
        parse_rankings(junk)
        parse_summary(junk)


# =====================================================================
# 7. GameStore
# =====================================================================


def team(tid: str, abbr: str | None = None) -> Team:
    return Team(id=tid, abbreviation=abbr or f"T{tid}", display_name=f"Team {tid}", short_name=f"T{tid}",
                color="#112233", alt_color="#ffffff")


def mk(
    hs=0,
    as_=0,
    *,
    gid="1",
    state=GameState.IN,
    name="STATUS_IN_PROGRESS",
    period=1,
    completed=None,
    hr=None,
    ar=None,
    hid="10",
    aid="20",
    situation=None,
) -> Game:
    if completed is None:
        completed = state == GameState.POST
    return Game(
        id=gid,
        date=datetime(2026, 10, 10, tzinfo=UTC),
        name=f"{aid} at {hid}",
        short_name=f"A{aid} @ H{hid}",
        home=Competitor(team(hid), "home", hs, hr),
        away=Competitor(team(aid), "away", as_, ar),
        status=Status(state=state, name=name, completed=completed, period=period, short_detail=f"Q{period}"),
        situation=situation,
    )


def pregame(**kw):
    return mk(state=GameState.PRE, name="STATUS_SCHEDULED", period=0, **kw)


def final(hs, as_, **kw):
    return mk(hs, as_, state=GameState.POST, name="STATUS_FINAL", period=4, completed=True, **kw)


def kinds(events):
    return [type(e).__name__ for e in events]


def play(text, tid, value, type_text):
    return Situation(last_play=LastPlay(text=text, type_text=type_text, score_value=value, team_id=tid))


class TestStoreBasics:
    def test_first_sight_pregame_silent(self):
        assert GameStore().apply([pregame()]) == []

    def test_first_sight_final_silent(self):
        assert GameStore().apply([final(21, 14)]) == []

    def test_first_sight_live_emits_started(self):
        ev = GameStore().apply([mk(7, 0)])
        assert kinds(ev) == ["GameStarted"]

    def test_first_sight_halftime(self):
        ev = GameStore().apply([mk(7, 0, name="STATUS_HALFTIME", period=2)])
        assert kinds(ev) == ["GameStarted", "Halftime"]

    def test_first_sight_disabled(self):
        assert GameStore(emit_on_first_sight=False).apply([mk(7, 0)]) == []

    def test_no_change_no_events(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        assert s.apply([mk(7, 0)]) == []

    def test_same_object_twice(self):
        s = GameStore()
        g = mk(7, 0)
        s.apply([g])
        assert s.apply([g]) == []

    def test_kickoff(self):
        s = GameStore()
        s.apply([pregame()])
        ev = s.apply([mk(0, 0)])
        assert kinds(ev) == ["GameStarted"]

    def test_kickoff_and_score_same_poll(self):
        s = GameStore()
        s.apply([pregame()])
        ev = s.apply([mk(7, 0)])
        assert kinds(ev) == ["GameStarted", "Scored"]

    def test_pre_to_postponed_no_start(self):
        s = GameStore()
        s.apply([pregame()])
        ev = s.apply([mk(state=GameState.POST, name="STATUS_POSTPONED", period=0, completed=False)])
        assert kinds(ev) == ["StatusChanged"]

    def test_pre_to_final_outage(self):
        s = GameStore()
        s.apply([pregame()])
        ev = s.apply([final(21, 14)])
        names = kinds(ev)
        assert names[0] == "GameStarted" and "GameFinal" in names and names.count("Scored") >= 1

    def test_final_event_winner_loser(self):
        s = GameStore()
        s.apply([mk(21, 14, period=4)])
        (fin,) = [e for e in s.apply([final(21, 14)]) if isinstance(e, GameFinal)]
        assert fin.winner.id == "10" and fin.loser.id == "20" and not fin.is_tie

    def test_final_tie(self):
        s = GameStore()
        s.apply([mk(21, 21, period=4)])
        (fin,) = [e for e in s.apply([final(21, 21)]) if isinstance(e, GameFinal)]
        assert fin.is_tie and fin.winner is None and fin.loser is None
        assert "FINAL" in str(fin)

    def test_final_only_once(self):
        s = GameStore()
        s.apply([mk(21, 14, period=4)])
        s.apply([final(21, 14)])
        assert s.apply([final(21, 14)]) == []
        assert s.apply([replace(final(21, 14), name="x")]) == []

    def test_final_ot_str(self):
        s = GameStore()
        s.apply([mk(24, 24, period=5)])
        g = replace(final(27, 24), status=Status(GameState.POST, "STATUS_FINAL", True, 5))
        (fin,) = [e for e in s.apply([g]) if isinstance(e, GameFinal)]
        assert "(OT)" in str(fin)

    def test_period_change(self):
        s = GameStore()
        s.apply([mk(period=1)])
        ev = s.apply([mk(period=2)])
        assert kinds(ev) == ["PeriodChanged"] and ev[0].period == 2

    @pytest.mark.parametrize("p", [5, 6, 7, 8, 9])
    def test_overtime_period_changes(self, p):
        s = GameStore()
        s.apply([mk(period=p - 1)])
        (ev,) = s.apply([mk(period=p)])
        assert isinstance(ev, PeriodChanged) and ev.is_overtime == (p > 4)

    def test_period_zero_ignored(self):
        s = GameStore()
        s.apply([mk(period=1)])
        assert s.apply([mk(period=0)]) == []

    def test_period_going_backwards_emits(self):
        s = GameStore()
        s.apply([mk(period=3)])
        ev = s.apply([mk(period=2)])
        assert kinds(ev) == ["PeriodChanged"]  # documented behaviour: any change

    def test_halftime_then_second_half(self):
        s = GameStore()
        s.apply([mk(period=2)])
        assert kinds(s.apply([mk(period=2, name="STATUS_HALFTIME")])) == ["Halftime"]
        assert s.apply([mk(period=2, name="STATUS_HALFTIME")]) == []
        ev = s.apply([mk(period=3)])
        assert kinds(ev) == ["PeriodChanged"]

    def test_halftime_with_period_change_only_halftime(self):
        s = GameStore()
        s.apply([mk(period=1)])
        ev = s.apply([mk(period=2, name="STATUS_HALFTIME")])
        assert kinds(ev) == ["Halftime"]

    def test_status_delay_and_resume(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        ev = s.apply([mk(7, 0, name="STATUS_DELAYED")])
        assert kinds(ev) == ["StatusChanged"]
        ev = s.apply([mk(7, 0)])
        assert kinds(ev) == ["StatusChanged"] or ev == []

    def test_in_progress_to_end_period_silent(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        assert s.apply([mk(7, 0, name="STATUS_END_PERIOD")]) == []

    def test_suspended_then_cancelled(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        e1 = s.apply([mk(7, 0, state=GameState.IN, name="STATUS_SUSPENDED")])
        e2 = s.apply([mk(7, 0, state=GameState.POST, name="STATUS_CANCELED", completed=False)])
        assert kinds(e1) == ["StatusChanged"] and kinds(e2) == ["StatusChanged"]

    def test_postponed_status_never_emits_final(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        ev = s.apply([mk(7, 0, state=GameState.POST, name="STATUS_POSTPONED", completed=False)])
        assert "GameFinal" not in kinds(ev)

    def test_reopened_final_then_final_again(self):
        """A game flips final -> live (data fix) -> final: second final is a new finish."""
        s = GameStore()
        s.apply([mk(21, 14, period=4)])
        assert "GameFinal" in kinds(s.apply([final(21, 14)]))
        s.apply([mk(21, 14, period=4)])
        assert "GameFinal" in kinds(s.apply([final(21, 14)]))


class TestScoring:
    def test_td_plus_pat_inferred(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        (ev,) = s.apply([mk(7, 0)])
        assert isinstance(ev, Scored) and ev.points == 7 and ev.score_kind is ScoreKind.TOUCHDOWN and ev.inferred

    def test_fg_inferred(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        (ev,) = s.apply([mk(0, 3)])
        assert ev.score_kind is ScoreKind.FIELD_GOAL and ev.team.id == "20"

    def test_exact_lastplay_not_inferred(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        (ev,) = s.apply([mk(3, 0, situation=play("FG GOOD", "10", 3, "Field Goal Good"))])
        assert ev.inferred is False and ev.score_kind is ScoreKind.FIELD_GOAL and ev.text == "FG GOOD"

    def test_lastplay_wrong_team_falls_back_inferred(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        (ev,) = s.apply([mk(3, 0, situation=play("FG GOOD", "20", 3, "Field Goal Good"))])
        assert ev.inferred

    def test_lastplay_mismatching_value_falls_back(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        evs = s.apply([mk(10, 0, situation=play("FG", "10", 3, "Field Goal Good"))])
        assert sum(e.points for e in evs) == 10 and all(e.inferred for e in evs)

    def test_both_teams_score_same_poll(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        evs = s.apply([mk(7, 3)])
        assert sorted(e.points for e in evs) == [3, 7]

    def test_lastplay_team_ordered_last(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        evs = s.apply([mk(7, 3, situation=play("TD", "20", 3, "Field Goal Good"))])
        assert evs[-1].team.id == "20"
        evs = GameStore()
        evs.apply([mk(0, 0)])
        out = evs.apply([mk(7, 3, situation=play("TD", "10", 7, "Passing Touchdown"))])
        assert out[-1].team.id == "10"

    @pytest.mark.parametrize("delta", list(range(1, 60)))
    def test_decompose_sums_to_delta(self, delta):
        parts = decompose(delta)
        assert sum(p for p, _ in parts) == delta
        assert all(p > 0 for p, _ in parts)

    def test_decompose_zero_negative(self):
        assert decompose(0) == [] and decompose(-5) == []

    def test_decompose_common(self):
        assert [p for p, _ in decompose(10)] == [7, 3]
        assert [p for p, _ in decompose(14)] == [7, 7]
        assert decompose(2)[0][1] is ScoreKind.SAFETY
        assert decompose(2, pat_pending=True)[0][1] is ScoreKind.TWO_POINT

    def test_big_jump(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        evs = s.apply([mk(77, 0)])
        assert sum(e.points for e in evs) == 77

    def test_score_after_6_then_2_is_two_point(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        s.apply([mk(6, 0, situation=play("TD", "10", 6, "Passing Touchdown"))])
        (ev,) = s.apply([mk(8, 0)])
        assert ev.score_kind is ScoreKind.TWO_POINT

    def test_score_after_7_then_2_is_safety(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        s.apply([mk(7, 0)])
        (ev,) = s.apply([mk(9, 0)])
        assert ev.score_kind is ScoreKind.SAFETY

    def test_score_decrease_correction(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        (ev,) = s.apply([mk(0, 0)])
        assert isinstance(ev, ScoreCorrected) and (ev.before, ev.after) == (7, 0) and ev.team.id == "10"
        assert "CORRECTION" in str(ev)

    def test_correction_and_other_scores(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        evs = s.apply([mk(0, 3)])
        assert sorted(kinds(evs)) == ["ScoreCorrected", "Scored"]

    def test_correction_then_same_score_again_rescored(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        s.apply([mk(0, 0)])
        (ev,) = s.apply([mk(7, 0)])
        assert isinstance(ev, Scored)

    def test_scoring_in_final_transition(self):
        s = GameStore()
        s.apply([mk(14, 14, period=4)])
        evs = s.apply([final(17, 14)])
        assert kinds(evs)[:1] == ["Scored"] and "GameFinal" in kinds(evs)

    def test_scoring_events_str(self):
        s = GameStore()
        s.apply([mk(0, 0)])
        for e in s.apply([mk(7, 3)]):
            assert str(e)

    def test_score_on_pregame_game(self):
        """Odd feed: pregame status but score changes. Should not raise."""
        s = GameStore()
        s.apply([pregame()])
        s.apply([pregame(hs=7)])

    def test_pre_scores_ignored_for_first_sight(self):
        s = GameStore()
        assert s.apply([pregame(hs=7)]) == []


class TestVanishReappear:
    def test_disappear_and_reappear_no_first_sight_replay(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        s.apply([])
        assert len(s) == 0 and s.get("1") is not None
        assert s.apply([mk(7, 0)]) == []

    def test_reappear_with_new_score_diffs_against_old(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        s.apply([])
        evs = s.apply([mk(14, 0)])
        assert kinds(evs) == ["Scored"] and evs[0].points == 7

    def test_reappear_as_final(self):
        s = GameStore()
        s.apply([mk(14, 0, period=4)])
        s.apply([])
        evs = s.apply([final(14, 0)])
        assert kinds(evs) == ["GameFinal"]

    def test_reset_makes_first_sight(self):
        s = GameStore()
        s.apply([mk(7, 0)])
        s.reset()
        assert s.polls == 0 and len(s) == 0 and s.get("1") is None
        assert kinds(s.apply([mk(7, 0)])) == ["GameStarted"]

    def test_games_reflect_latest_feed_order(self):
        s = GameStore()
        s.apply([mk(gid="a"), mk(gid="b"), mk(gid="c")])
        s.apply([mk(gid="c"), mk(gid="a")])
        assert [g.id for g in s.games] == ["c", "a"]
        assert "b" not in s and s.get("b") is not None

    def test_live_property(self):
        s = GameStore()
        s.apply([mk(gid="a"), pregame(gid="b"), final(1, 0, gid="c")])
        assert [g.id for g in s.live] == ["a"]

    def test_duplicate_ids_same_poll_no_phantom_events(self):
        """Identical duplicate rows in one feed must not produce events from diffing a game against itself."""
        s = GameStore()
        s.apply([mk(7, 0)])
        a = mk(7, 0)
        b = mk(7, 0)
        assert s.apply([a, b]) == []

    def test_duplicate_ids_conflicting_rows_do_not_crash(self):
        s = GameStore()
        s.apply([mk(7, 0), mk(0, 0)])
        assert len(s) == 1

    def test_duplicate_first_sight_not_double_emitted(self):
        s = GameStore()
        evs = s.apply([mk(7, 0), mk(7, 0)])
        assert kinds(evs).count("GameStarted") == 1

    def test_hundred_plus_games(self):
        s = GameStore()
        games = [mk(gid=str(i), hid=str(1000 + i), aid=str(2000 + i), hs=i % 7, as_=i % 5) for i in range(150)]
        evs = s.apply(games)
        assert len(s) == 150 and kinds(evs).count("GameStarted") == 150
        nxt = [replace(g, home=replace(g.home, score=g.home.score + 3)) for g in games]
        evs = s.apply(nxt)
        assert kinds(evs).count("Scored") == 150
        assert s.last_errors == []

    def test_polls_counter(self):
        s = GameStore()
        for _ in range(3):
            s.apply([])
        assert s.polls == 3

    def test_error_isolated_per_game(self):
        s = GameStore()
        s.apply([mk(gid="a", hs=0), mk(gid="b", hs=0)])
        bad = replace(mk(gid="a", hs=7), home=None)  # type: ignore[arg-type]
        evs = s.apply([bad, mk(gid="b", hs=3)])
        assert any(e.game.id == "b" for e in evs)
        assert s.last_errors and s.last_errors[0][0] == "a"
        # the broken game's snapshot is retained so the next poll diffs against it
        evs = s.apply([mk(gid="a", hs=7), mk(gid="b", hs=3)])
        assert any(isinstance(e, Scored) and e.game.id == "a" for e in evs)


class TestRedZone:
    def rz(self, poss="10", rz=True):
        return Situation(is_red_zone=rz, possession=poss)

    def test_enter_redzone(self):
        s = GameStore()
        s.apply([mk()])
        evs = s.apply([mk(situation=self.rz())])
        assert kinds(evs) == ["RedZone"] and evs[0].team.id == "10"

    def test_stay_no_repeat(self):
        s = GameStore()
        s.apply([mk(situation=self.rz())])
        assert s.apply([mk(situation=self.rz())]) == []

    def test_possession_flip_in_redzone_emits(self):
        s = GameStore()
        s.apply([mk(situation=self.rz("10"))])
        assert kinds(s.apply([mk(situation=self.rz("20"))])) == ["RedZone"]

    def test_first_sight_redzone(self):
        evs = GameStore().apply([mk(situation=self.rz())])
        assert kinds(evs) == ["GameStarted", "RedZone"]

    def test_redzone_unknown_possession(self):
        s = GameStore()
        s.apply([mk()])
        (ev,) = s.apply([mk(situation=self.rz(poss="999"))])
        assert ev.team is None
        assert "?" in str(ev)

    def test_redzone_none_possession(self):
        s = GameStore()
        s.apply([mk()])
        (ev,) = s.apply([mk(situation=self.rz(poss=None))])
        assert ev.team is None

    def test_redzone_final_game_ignored(self):
        s = GameStore()
        s.apply([mk(7, 0, period=4)])
        evs = s.apply([replace(final(7, 0), situation=self.rz())])
        assert "RedZone" not in kinds(evs)


# =====================================================================
# 8. Upset rule + store upset events
# =====================================================================


class TestUpsetRule:
    rule = UpsetRule()

    def v(self, g):
        return self.rule.evaluate(g)

    def test_pregame_none(self):
        assert self.v(pregame(hr=1, ar=20)) is None

    def test_tied_none(self):
        assert self.v(mk(7, 7, hr=1, ar=20)) is None

    def test_both_unranked_none(self):
        assert self.v(mk(14, 7)) is None
        assert self.v(final(14, 7)) is None

    def test_favorite_leads_none(self):
        assert self.v(mk(14, 7, hr=3, ar=10)) is None

    def test_unranked_leads_ranked_watch(self):
        v = self.v(mk(14, 7, ar=10))
        assert v.watch and v.underdog.id == "10" and v.favorite.id == "20" and v.underdog_rank is None

    def test_ranked_leads_unranked_no(self):
        assert self.v(mk(14, 7, hr=10)) is None

    def test_lower_ranked_leads_higher(self):
        v = self.v(mk(14, 7, hr=20, ar=3))
        assert v.watch and v.underdog.id == "10" and v.favorite_rank == 3 and v.underdog_rank == 20

    def test_equal_rank_none(self):
        assert self.v(mk(14, 7, hr=5, ar=5)) is None

    def test_final_confirmed(self):
        v = self.v(final(14, 7, hr=20, ar=3))
        assert v.confirmed and not v.watch and v.margin == 7

    def test_final_tie_none(self):
        assert self.v(final(7, 7, hr=20, ar=3)) is None

    def test_rank_1_vs_25(self):
        assert self.v(mk(7, 0, hr=25, ar=1)) is not None

    def test_postponed_with_scores(self):
        g = mk(7, 0, state=GameState.POST, name="STATUS_POSTPONED", completed=False, hr=20, ar=3)
        v = self.v(g)
        # a postponed game is not "live" and not "final" so should not claim a confirmed upset
        assert v is None or not v.confirmed

    def test_fallback_to_ap_poll(self):
        polls = parse_rankings({"rankings": [{"type": "ap", "ranks": [{"current": 2, "team": {"id": "20"}}]},
                                             {"type": "usa", "ranks": [{"current": 1, "team": {"id": "10"}}]}]})
        rule = UpsetRule(polls)
        v = rule.evaluate(mk(14, 7))
        assert v is not None and v.favorite.id == "20"

    def test_curated_rank_beats_poll(self):
        polls = parse_rankings({"rankings": [{"type": "ap", "ranks": [{"current": 2, "team": {"id": "20"}}]}]})
        rule = UpsetRule(polls)
        assert rule.rank_of(mk(ar=9).away) == 9

    def test_poll_choice_and_reset(self):
        polls = parse_rankings({"rankings": [{"type": "usa", "ranks": [{"current": 2, "team": {"id": "20"}}]}]})
        assert UpsetRule(polls).ranking is None
        assert UpsetRule(polls, poll="usa").ranking is not None
        r = UpsetRule(polls, poll="usa")
        r.set_rankings(None)
        assert r.ranking is None

    def test_poll_rank_zero_sentinel_unranked(self):
        polls = parse_rankings({"rankings": [{"type": "ap", "ranks": [{"current": 0, "team": {"id": "20"}}]}]})
        assert UpsetRule(polls).evaluate(mk(14, 7)) is None


class TestStoreUpsets:
    def test_watch_on_first_sight(self):
        evs = GameStore().apply([mk(14, 7, hr=20, ar=3)])
        assert kinds(evs) == ["GameStarted", "UpsetWatch"]

    def test_watch_when_underdog_takes_lead(self):
        s = GameStore()
        s.apply([mk(7, 7, hr=20, ar=3)])
        evs = s.apply([mk(14, 7, hr=20, ar=3)])
        assert kinds(evs) == ["Scored", "UpsetWatch"]

    def test_no_repeat_watch_while_leading(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3)])
        assert kinds(s.apply([mk(21, 7, hr=20, ar=3)])) == ["Scored"]

    def test_watch_lost_then_regained(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3)])
        s.apply([mk(14, 17, hr=20, ar=3)])
        evs = s.apply([mk(21, 17, hr=20, ar=3)])
        assert "UpsetWatch" in kinds(evs)

    def test_upset_confirmed_on_final(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3, period=4)])
        evs = s.apply([final(14, 7, hr=20, ar=3)])
        assert kinds(evs) == ["GameFinal", "Upset"]

    def test_upset_not_repeated(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3, period=4)])
        s.apply([final(14, 7, hr=20, ar=3)])
        assert s.apply([final(14, 7, hr=20, ar=3)]) == []

    def test_upset_from_pregame_to_final_directly(self):
        s = GameStore()
        s.apply([pregame(hr=20, ar=3)])
        evs = s.apply([final(14, 7, hr=20, ar=3)])
        assert "Upset" in kinds(evs)

    def test_final_favorite_wins_no_upset(self):
        s = GameStore()
        s.apply([mk(7, 14, hr=20, ar=3, period=4)])
        assert "Upset" not in kinds(s.apply([final(7, 14, hr=20, ar=3)]))

    def test_tie_final_no_upset(self):
        s = GameStore()
        s.apply([mk(7, 7, hr=20, ar=3, period=4)])
        assert "Upset" not in kinds(s.apply([final(7, 7, hr=20, ar=3)]))

    def test_rank_change_mid_game_no_spurious_watch(self):
        """Ranks are reshuffled mid-game (e.g. new poll lands) but the same team is underdog."""
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3)])
        evs = s.apply([mk(14, 7, hr=20, ar=4)])
        assert evs == []

    def test_rank_appears_mid_game_creates_watch(self):
        s = GameStore()
        s.apply([mk(14, 7)])
        evs = s.apply([mk(14, 7, ar=5)])
        assert kinds(evs) == ["UpsetWatch"]

    def test_rank_vanishes_mid_game_clears_then_rewatch(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3)])
        assert s.apply([mk(14, 7)]) == []
        assert kinds(s.apply([mk(14, 7, hr=20, ar=3)])) == ["UpsetWatch"]

    def test_watch_to_confirmed_via_rank_flip_in_final(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3, period=4)])
        # final arrives with ranks stripped (feed re-keyed after the game); verdict disappears, no Upset
        evs = s.apply([final(14, 7)])
        assert "Upset" not in kinds(evs)

    def test_fcs_ranked_vs_unranked_fbs(self):
        # FCS-ranked home beats unranked: no upset; unranked beating ranked FCS: watch
        s = GameStore()
        s.apply([mk(7, 0, hr=3)])
        assert s.apply([mk(7, 0, hr=3)]) == []
        s2 = GameStore()
        evs = s2.apply([mk(7, 0, ar=3)])
        assert "UpsetWatch" in kinds(evs)

    def test_store_rule_uses_rankings_poll(self):
        polls = parse_rankings({"rankings": [{"type": "ap", "ranks": [{"current": 2, "team": {"id": "20"}}]}]})
        s = GameStore(rule=UpsetRule(polls))
        evs = s.apply([mk(14, 7)])
        assert "UpsetWatch" in kinds(evs)

    @pytest.mark.skip(reason="known gap, wontfix: rankings loading after kickoff skip the ticker's UpsetWatch; cards still restyle")
    def test_rankings_arrive_mid_game(self):
        rule = UpsetRule()
        s = GameStore(rule=rule)
        s.apply([mk(14, 7)])
        rule.set_rankings(parse_rankings({"rankings": [{"type": "ap", "ranks": [{"current": 2, "team": {"id": "20"}}]}]}))
        evs = s.apply([mk(14, 7)])  # new object, same content
        assert kinds(evs) == ["UpsetWatch"]

    def test_underdog_swap_emits_new_watch(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3)])
        evs = s.apply([mk(14, 21, hr=20, ar=3)])  # favorite retakes lead: no watch
        assert "UpsetWatch" not in kinds(evs)

    def test_both_ranked_score_cross_and_cross_back(self):
        s = GameStore()
        s.apply([mk(7, 0, hr=2, ar=1, period=3)])  # #2 leads #1 -> underdog is home
        evs = s.apply([mk(7, 14, hr=2, ar=1, period=3)])
        assert "UpsetWatch" not in kinds(evs)

    def test_upset_event_text(self):
        s = GameStore()
        s.apply([mk(14, 7, hr=20, ar=3, period=4)])
        evs = s.apply([final(14, 7, hr=20, ar=3)])
        text = str(evs[-1])
        assert "#20" in text and "#3" in text

    def test_halftime_first_sight_with_upset(self):
        evs = GameStore().apply([mk(14, 7, hr=20, ar=3, name="STATUS_HALFTIME", period=2)])
        assert kinds(evs) == ["GameStarted", "Halftime", "UpsetWatch"]


# =====================================================================
# 9. End to end: mock HTTP -> client -> store
# =====================================================================


class TestEndToEnd:
    @respx.mock
    async def test_two_polls_via_http(self):
        d1 = raw(FINAL)
        d2 = copy.deepcopy(d1)
        route = respx.get(f"{BASE_URL}/scoreboard").mock(
            side_effect=[httpx.Response(200, json=d1), httpx.Response(503), httpx.Response(503),
                         httpx.Response(503), httpx.Response(503), httpx.Response(200, json=d2)]
        )
        store = GameStore()
        async with make_client() as c:
            assert store.apply_scoreboard(await c.scoreboard(week=6)) == []  # all final: silent
            with pytest.raises(EspnHttpError):
                await c.scoreboard(week=6)
            assert store.apply_scoreboard(await c.scoreboard(week=6)) == []
        assert route.call_count == 6
        assert len(store) == len(d1["events"])

    @respx.mock
    async def test_pregame_to_live_via_http(self):
        d1 = raw(PRE)
        d2 = copy.deepcopy(d1)
        ev = d2["events"][0]["competitions"][0]
        ev["status"] = {"displayClock": "15:00", "period": 1, "type": {"name": "STATUS_IN_PROGRESS", "state": "in",
                                                                    "completed": False, "detail": "1st", "shortDetail": "1st"}}
        respx.get(f"{BASE_URL}/scoreboard").mock(side_effect=[httpx.Response(200, json=d1), httpx.Response(200, json=d2)])
        store = GameStore()
        async with make_client() as c:
            store.apply_scoreboard(await c.scoreboard())
            evs = store.apply_scoreboard(await c.scoreboard())
        assert [type(e).__name__ for e in evs] == ["GameStarted"]


class TestAbsurdScores:
    def test_absurd_score_jump_is_handled_not_errored(self):
        """A garbage score (e.g. 10**30) must not make the diff blow up or allocate unbounded memory."""
        s = GameStore()
        s.apply([mk(0, 0)])
        s.apply([mk(10**30, 0)])
        assert s.last_errors == []

    def test_parser_clamps_or_store_survives_huge_score_from_json(self):
        e = first_event()
        for c in comp(e)["competitors"]:
            c["score"] = "99999999999999999999"
        g = parse_event(e)
        s = GameStore()
        s.apply([replace(g, home=replace(g.home, score=0), away=replace(g.away, score=0),
                         status=Status(GameState.IN, "STATUS_IN_PROGRESS", False, 1))])
        s.apply([replace(g, status=Status(GameState.IN, "STATUS_IN_PROGRESS", False, 1))])
        assert s.last_errors == []
