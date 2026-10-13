"""UAT: scheduler and app resilience over simulated time.

The scheduler's intervals are presence based (live = someone at the machine, idle = away), not game based;
the tests below follow the code, and say so where the distinction matters.
"""
from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta

import httpx
import pytest
import respx

from cfbtui.app import CfbApp
from cfbtui.config import Config, parse_config
from cfbtui.espn.client import EspnHttpError, EspnNetworkError
from cfbtui.espn.models import GameState, Scoreboard, Status
from cfbtui.poll import RANKINGS_RETRY, FreshnessState, PollIntervals, PollScheduler
from cfbtui.state.store import GameStore
from cfbtui.ui.widgets.game_card import GameCard
from cfbtui.ui.widgets.ticker import CAP, Ticker
from cfbtui.update import RELEASES_URL, UpdateInfo, check_for_update
from tests.fakes import FakeClient, FakeClock, load_board, load_rankings

LIVE, IDLE, BMAX = 20.0, 120.0, 120.0
SIZE = (140, 44)
FAST = PollIntervals(live=0.02, idle=0.02, backoff_max=0.05)


def board(name: str) -> Scoreboard:
    return load_board(f"pairs/{name}.json")


def make(client, *, present: bool = True, intervals: PollIntervals | None = None, **kw):
    clock = FakeClock()
    results: list = []
    state = {"present": present}
    sched = PollScheduler(
        client,
        GameStore(),
        intervals=intervals or PollIntervals(live=LIVE, idle=IDLE, backoff_max=BMAX),
        clock=clock,
        now=clock.now,
        on_result=results.append,
        idle_for=lambda: 0.0 if state["present"] else 10_000.0,
        **kw,
    )
    return sched, clock, results, state


async def cycle(sched: PollScheduler, clock: FakeClock):
    """One poll, then let the scheduler's own next delay pass. Returns (result, delay waited)."""
    result = await sched.poll_once()
    delay = sched.next_delay()
    clock.advance(delay)
    return result, delay


def with_state(sc: Scoreboard, state: GameState, name: str, completed: bool = False) -> Scoreboard:
    games = tuple(
        dataclasses.replace(g, status=Status(state=state, name=name, completed=completed, period=2, clock="5:00"))
        for g in sc.games
    )
    return dataclasses.replace(sc, games=games)


def with_scores(sc: Scoreboard, away: int, home: int) -> Scoreboard:
    games = tuple(
        dataclasses.replace(
            g, away=dataclasses.replace(g.away, score=away), home=dataclasses.replace(g.home, score=home)
        )
        for g in sc.games
    )
    return dataclasses.replace(sc, games=games)


async def wait_for(pilot, predicate, timeout: float = 4.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await pilot.pause(0.02)


# --- default intervals ------------------------------------------------------------


def test_default_intervals_are_20_and_120():
    iv = PollIntervals()
    assert (iv.live, iv.idle) == (20.0, 120.0)


def test_user_with_no_config_gets_20_and_120():
    assert Config().poll.live == 20.0 and Config().poll.idle == 120.0
    cfg, warnings = parse_config({})
    assert (cfg.poll.live, cfg.poll.idle) == (20.0, 120.0) and not warnings
    app = CfbApp(client=FakeClient(board("touchdown_before")))
    assert (app.scheduler.intervals.live, app.scheduler.intervals.idle) == (20.0, 120.0)


async def test_present_polls_every_20_and_away_every_120():
    sched, clock, _, state = make(FakeClient(board("touchdown_before")))
    delays = [(await cycle(sched, clock))[1] for _ in range(3)]
    assert delays == [20.0] * 3
    state["present"] = False
    delays = [(await cycle(sched, clock))[1] for _ in range(3)]
    assert delays == [120.0] * 3
    state["present"] = True
    assert (await cycle(sched, clock))[1] == 20.0


async def test_cadence_follows_presence_not_game_state():
    """Live game, nobody home: slow. Everything final, someone home: fast."""
    live = board("touchdown_before")
    sched, clock, _, _ = make(FakeClient(live), present=False)
    assert (await cycle(sched, clock))[1] == IDLE
    final = board("final_after")
    sched, clock, _, _state = make(FakeClient(final), present=True)
    assert (await cycle(sched, clock))[1] == LIVE


async def test_game_in_progress_then_final_keeps_polling_and_reports_events():
    client = FakeClient(board("touchdown_before"), board("final_before"), board("final_after"))
    sched, clock, results, _ = make(client)
    for _ in range(3):
        await cycle(sched, clock)
    assert [r.ok for r in results] == [True] * 3
    assert sched.store.games[0].is_final
    assert not sched.store.live


async def test_away_user_gets_a_poll_pulled_forward_to_kickoff():
    pre = board("game_start_before")
    sched, clock, _, _state = make(FakeClient(pre), present=False)
    game = pre.games[0]
    clock.wall = game.date - timedelta(seconds=45)
    await sched.poll_once()
    assert sched.next_delay() == pytest.approx(45.0)
    clock.wall = game.date + timedelta(hours=9)  # long overdue: never a zero or negative delay
    assert sched.next_delay() == IDLE


# --- backoff ----------------------------------------------------------------------


async def test_backoff_doubles_to_the_cap_and_recovery_resets_it():
    err = EspnNetworkError("down")
    good = board("touchdown_before")
    client = FakeClient(good, err)
    sched, clock, _results, _ = make(client)
    await cycle(sched, clock)  # good
    delays = [(await cycle(sched, clock))[1] for _ in range(6)]
    assert delays[:3] == [40.0, 80.0, 120.0]
    assert all(d == BMAX for d in delays[2:]), delays
    assert sched.freshness().state is FreshnessState.ERROR
    assert sched.freshness().failures == 6
    client.push(good)
    client._last = good
    client._script.clear()
    result, delay = await cycle(sched, clock)
    assert result.ok and delay == LIVE
    assert sched.freshness().failures == 0


async def test_backoff_never_exceeds_cap_over_a_long_outage():
    sched, clock, _, _ = make(FakeClient(board("touchdown_before"), EspnHttpError(503, "u")))
    await cycle(sched, clock)
    for _ in range(500):
        _, d = await cycle(sched, clock)
        assert LIVE <= d <= BMAX
    assert sched.freshness().failures == 500


async def test_backoff_with_a_cap_below_the_interval_never_goes_below_normal():
    iv = PollIntervals(live=20.0, idle=120.0, backoff_max=5.0)
    sched, clock, _, _ = make(FakeClient(EspnNetworkError("x")), intervals=iv)
    for _ in range(5):
        _, d = await cycle(sched, clock)
        assert d >= 5.0


async def test_offline_at_start_retries_at_live_pace_then_recovers():
    good = board("touchdown_before")
    client = FakeClient(*([EspnNetworkError("offline")] * 3), good)
    sched, clock, _results, _ = make(client, present=False)  # away + offline: still not 2 minutes
    delays = []
    for _ in range(3):
        r, d = await cycle(sched, clock)
        assert not r.ok and r.scoreboard is None
        assert r.freshness.state is FreshnessState.ERROR and r.freshness.age is None
        delays.append(d)
    assert delays[0] == 2 * LIVE and all(d <= BMAX for d in delays)  # fast retry, not the 120s away interval
    r, _ = await cycle(sched, clock)
    assert r.ok and len(sched.store) == 1 and r.freshness.state is FreshnessState.FRESH


# --- generation ---------------------------------------------------------------------


class GatedClient(FakeClient):
    """Holds the first scoreboard call until released."""

    def __init__(self, *script, **kw):
        super().__init__(*script, **kw)
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.gate_next = True

    async def scoreboard(self, *, week=None, group=80):
        if self.gate_next:
            self.gate_next = False
            self.entered.set()
            await self.gate.wait()
        return await super().scoreboard(week=week, group=group)


async def test_poll_in_flight_when_user_switches_is_dropped():
    client = GatedClient(board("touchdown_before"))
    sched, _clock, results, _ = make(client, week=5)
    task = asyncio.create_task(sched.poll_once())
    await client.entered.wait()
    sched.switch(week=6)
    client.gate.set()
    result = await task
    assert result.scoreboard is None and result.error is None
    assert results == [], "a dropped poll must not be reported"
    assert len(sched.store) == 0 and sched.scoreboard is None
    assert sched.freshness().state is FreshnessState.LOADING
    nxt = await sched.poll_once()
    assert nxt.ok and nxt.generation == sched.generation == 1 and len(sched.store) == 1


async def test_failure_of_a_poll_the_user_left_is_not_counted():
    class BoomGate(GatedClient):
        async def scoreboard(self, *, week=None, group=80):
            self.entered.set()
            await self.gate.wait()
            raise EspnNetworkError("late failure")

    client = BoomGate()
    sched, _clock, results, _ = make(client)
    task = asyncio.create_task(sched.poll_once())
    await client.entered.wait()
    sched.switch(week=3, group=81)
    client.gate.set()
    await task
    assert sched.freshness().failures == 0 and results == []


async def test_run_loop_polls_the_new_week_right_after_switch():
    client = GatedClient(board("touchdown_before"))
    sched, *_ = make(client, intervals=FAST)
    runner = asyncio.create_task(sched.run())
    await client.entered.wait()
    sched.switch(week=9)
    client.gate.set()
    for _ in range(100):
        if any(k["week"] == 9 for k in client.kwargs):
            break
        await asyncio.sleep(0.01)
    sched.stop()
    await asyncio.wait_for(runner, 2)
    assert {"week": 9, "group": 80} in client.kwargs


# --- rankings -----------------------------------------------------------------------


async def test_rankings_failure_retries_on_schedule_without_hurting_scoreboard():
    client = FakeClient(board("touchdown_before"), rankings=EspnNetworkError("rank down"))
    sched, clock, _results, _ = make(client)
    for _ in range(5):
        r, _ = await cycle(sched, clock)
        assert r.ok and r.freshness.state is FreshnessState.FRESH
    before = client.rankings_calls
    assert before == 1 + int(5 * LIVE // RANKINGS_RETRY)
    clock.advance(RANKINGS_RETRY)
    await sched.poll_once()
    assert client.rankings_calls == before + 1
    client._rankings = load_rankings()
    clock.advance(RANKINGS_RETRY)
    await sched.poll_once()
    await sched.poll_once()
    assert client.rankings_calls == before + 2, "stops asking once rankings load"


async def test_rankings_raising_a_weird_exception_does_not_break_polling():
    client = FakeClient(board("touchdown_before"), rankings=ValueError("bad rankings"))
    sched, _clock, _, _ = make(client)
    assert (await sched.poll_once()).ok


# --- unexpected exception types -------------------------------------------------------


@pytest.mark.parametrize("exc", [ValueError("v"), KeyError("k"), TypeError("t"), AttributeError("a"), IndexError("i"),
                                 ZeroDivisionError(), RuntimeError("r"), UnicodeDecodeError("u", b"", 0, 1, "x")])
async def test_unexpected_exception_types_become_error_results(exc):
    good = board("touchdown_before")
    sched, clock, _results, _ = make(FakeClient(good, exc, good))
    await cycle(sched, clock)
    r, _ = await cycle(sched, clock)
    assert not r.ok and isinstance(r.error, type(exc))
    assert sched.scoreboard is not None, "last good data stays"
    assert type(exc).__name__ in (r.freshness.error or "")
    r, _ = await cycle(sched, clock)
    assert r.ok and r.freshness.state is FreshnessState.FRESH


async def test_run_loop_survives_a_run_of_assorted_exceptions():
    good = board("touchdown_before")
    client = FakeClient(KeyError("x"), ValueError("y"), EspnNetworkError("z"), good)
    sched, *_ = make(client, intervals=FAST)
    runner = asyncio.create_task(sched.run())
    for _ in range(300):
        if client.scoreboard_calls >= 6:
            break
        await asyncio.sleep(0.01)
    assert not runner.done(), "the poll loop must still be alive"
    assert sched.scoreboard is not None
    sched.stop()
    await asyncio.wait_for(runner, 2)


class PoisonStore(GameStore):
    def apply_scoreboard(self, scoreboard):
        raise KeyError("store exploded")


async def test_store_exception_is_a_failed_poll_not_a_crash():
    clock = FakeClock()
    sched = PollScheduler(FakeClient(board("touchdown_before")), PoisonStore(), clock=clock, now=clock.now,
                          idle_for=lambda: 0.0)
    r = await sched.poll_once()
    assert not r.ok and isinstance(r.error, KeyError)


async def test_on_result_callback_runs_even_when_polling_failed():
    sched, _clock, results, _ = make(FakeClient(KeyError("k")))
    await sched.poll_once()
    assert len(results) == 1 and not results[0].ok


# --- stop ---------------------------------------------------------------------------


async def test_stop_ends_run_promptly_and_cleanly():
    sched, *_ = make(FakeClient(board("touchdown_before")), intervals=PollIntervals(live=60, idle=60, backoff_max=60))
    runner = asyncio.create_task(sched.run())
    await asyncio.sleep(0.05)
    sched.stop()
    await asyncio.wait_for(runner, 1)
    assert runner.exception() is None and not sched.polling


async def test_stop_before_run_makes_run_return_immediately():
    client = FakeClient(board("touchdown_before"))
    sched, *_ = make(client)
    sched.stop()
    await asyncio.wait_for(sched.run(), 1)
    assert client.scoreboard_calls == 0


async def test_stop_mid_fetch_exits_after_the_fetch():
    client = GatedClient(board("touchdown_before"))
    sched, *_ = make(client)
    runner = asyncio.create_task(sched.run())
    await client.entered.wait()
    sched.stop()
    client.gate.set()
    await asyncio.wait_for(runner, 1)
    assert client.scoreboard_calls == 1


async def test_cancelling_the_run_loop_mid_fetch_resets_polling_flag():
    client = GatedClient(board("touchdown_before"))
    sched, *_ = make(client)
    runner = asyncio.create_task(sched.run())
    await client.entered.wait()
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert sched.polling is False


# --- long run -----------------------------------------------------------------------


async def test_a_thousand_cycles_do_not_grow_state():
    base = board("touchdown_before")
    boards = [with_scores(base, i, i // 2) for i in range(1000)]
    client = FakeClient(*boards)
    sched, clock, _results, _ = make(client)
    sched.on_result = None  # a real app drains these; the test must not hoard them
    sizes = []
    for i in range(1000):
        await cycle(sched, clock)
        if i in (50, 999):
            sizes.append((len(sched.store._seen), len(sched.store._games), len(sched.store._pat_pending),
                          len(sched.store.last_errors)))
    assert sizes[0] == sizes[1] or all(b <= max(a, 1) for a, b in zip(sizes[0], sizes[1], strict=True))
    assert len(sched.store) == 1 and sched.polls == 1000
    for name, value in vars(sched).items():
        if isinstance(value, list | dict | set | tuple):
            assert len(value) < 10, name


async def test_a_thousand_cycles_with_alternating_errors_stay_bounded():
    good = board("touchdown_before")
    script = []
    for i in range(1000):
        script.append(good if i % 3 else EspnNetworkError("blip"))
    sched, clock, _, _ = make(FakeClient(*script))
    for _ in range(1000):
        _, d = await cycle(sched, clock)
        assert d <= BMAX
    assert len(sched.store) == 1


async def test_app_ticker_is_capped_over_many_scoring_polls():
    base = board("touchdown_before")
    boards = [with_scores(base, 7 * i, 3 * i) for i in range(1, 400)]
    client = FakeClient(*boards)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: client.scoreboard_calls >= 150, timeout=30)
        assert app.query_one(Ticker).entry_count <= CAP
        assert len(app.query(GameCard)) == 1


# --- app level ------------------------------------------------------------------------


async def test_app_survives_errors_of_every_kind_and_recovers():
    good = board("touchdown_before")
    client = FakeClient(KeyError("a"), ValueError("b"), EspnNetworkError("c"), good)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        assert app.last_result is not None


async def test_app_offline_at_start_shows_message_then_cards():
    good = board("touchdown_before")
    client = FakeClient(EspnNetworkError("offline"), EspnNetworkError("offline"), good)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: client.scoreboard_calls >= 1)
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)


async def test_app_week_switch_mid_poll_drops_the_old_week():
    client = GatedClient(board("touchdown_before"), board("final_after"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", week=5)
    async with app.run_test(size=SIZE) as pilot:
        await client.entered.wait()
        await pilot.press("right_square_bracket")
        client.gate.set()
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        assert app.scheduler.week == 6
        assert all(not g.is_live for g in app.store.games), "the old week's live board must not appear"
        assert app.query_one(Ticker).entry_count == 0


async def test_app_unmount_mid_poll_is_clean():
    client = GatedClient(board("touchdown_before"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE):
        await client.entered.wait()
    # leaving the context unmounts with a fetch still in flight; releasing it afterwards must not blow up
    client.gate.set()
    await asyncio.sleep(0.1)
    assert app.scheduler._stopped


async def test_app_unmount_right_after_poll_result_is_clean():
    client = FakeClient(board("touchdown_before"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: client.scoreboard_calls >= 3)
    await asyncio.sleep(0.1)


# --- update check ----------------------------------------------------------------------

URL = "https://github.com/WPTK/cfbtui/releases/tag/v9.0.0"


def rel(**over):
    body = {"tag_name": "v9.0.0", "html_url": URL, "draft": False, "prerelease": False}
    body.update(over)
    return body


@pytest.fixture
def gh():
    with respx.mock(assert_all_called=False) as router:
        yield router


def notified(app: CfbApp) -> list[str]:
    return [n.message for n in app._notifications]


async def run_with_check(check, *, wait=0.3):
    app = CfbApp(client=FakeClient(board("touchdown_before")), intervals=FAST, glyph_set="ascii", update_check=check)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        await pilot.pause(wait)
        assert len(app.query(GameCard)) == 1
        return notified(app)


async def test_update_check_none_is_silent():
    async def check():
        return None

    assert not [m for m in await run_with_check(check) if "available" in m]


async def test_update_check_raising_never_crashes_the_app():
    async def check():
        raise RuntimeError("boom")

    app = CfbApp(client=FakeClient(board("touchdown_before")), intervals=FAST, glyph_set="ascii", update_check=check)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        await pilot.pause(0.3)
        assert app.is_running and len(app.query(GameCard)) == 1


async def test_update_check_hanging_forever_does_not_block_the_app():
    async def check():
        await asyncio.sleep(3600)

    assert await run_with_check(check) is not None


async def test_update_check_newer_version_notifies():
    async def check():
        return UpdateInfo("9.0.0", URL)

    msgs = await run_with_check(check)
    assert any("9.0.0" in m and URL in m for m in msgs)


@pytest.mark.parametrize("url", ["[/]", "[bold]x", "https://x/[red]y[/red]", "[/nonsense]", "https://x/\x1b[31m", ""])
async def test_update_message_with_markup_in_the_url_does_not_crash(url):
    async def check():
        return UpdateInfo("9.0.0", url)

    await run_with_check(check)


async def test_update_flow_through_real_check_with_respx(gh):
    gh.get(RELEASES_URL).respond(200, json=rel())

    async def check():
        async with httpx.AsyncClient() as c:
            return await check_for_update("0.1.0", client=c)

    msgs = await run_with_check(check)
    assert any("9.0.0" in m for m in msgs)


@pytest.mark.parametrize(
    "tag",
    ["", "latest", "v", "vv9.0.0", "9", "9.0", "9.0.0.0", "9.0.0-rc1", "v9.0.0+build", "v9.0.x", " v9.0.0 ", "V9.0.0",
     "v-1.0.0", "v9..0", "v9.0.0\n", "v٩.0.0", "v².0.0", "v" + "9" * 5000 + ".0.0", "[red]v9.0.0", "💥",
     "v9.0.0\x00"],
)
async def test_malformed_tags_never_raise(gh, tag):
    gh.get(RELEASES_URL).respond(200, json=rel(tag_name=tag))
    result = await check_for_update("0.1.0")
    assert result is None or isinstance(result, UpdateInfo)


@pytest.mark.parametrize("tag", ["v9.0.0-rc1", "v9.0.0+build", "9.0", "latest", "v9.0.x"])
async def test_non_semver_tags_are_not_offered(gh, tag):
    gh.get(RELEASES_URL).respond(200, json=rel(tag_name=tag))
    assert await check_for_update("0.1.0") is None


async def test_leading_and_trailing_whitespace_in_tag_is_tolerated(gh):
    gh.get(RELEASES_URL).respond(200, json=rel(tag_name=" v9.0.0 "))
    info = await check_for_update("0.1.0")
    assert info is not None and info.version == "9.0.0"


@pytest.mark.parametrize("current", ["", "junk", "1.0", "1.0.0-dev", None])
async def test_odd_current_version_never_raises(gh, current):
    gh.get(RELEASES_URL).respond(200, json=rel())
    assert await check_for_update(current) is None


async def test_rate_limit_403_and_429_are_none(gh):
    for status in (403, 429):
        gh.get(RELEASES_URL).respond(status, json={"message": "API rate limit exceeded"},
                                      headers={"x-ratelimit-remaining": "0"})
        assert await check_for_update("0.1.0") is None


async def test_prerelease_and_draft_flags_in_odd_types(gh):
    gh.get(RELEASES_URL).respond(200, json=rel(prerelease=True))
    assert await check_for_update("0.1.0") is None
    gh.get(RELEASES_URL).respond(200, json=rel(draft="yes"))
    assert await check_for_update("0.1.0") is None


@pytest.mark.parametrize("body", [None, 5, [], [rel()], "x", {"tag_name": None, "html_url": None},
                                  {"tag_name": ["v9.0.0"], "html_url": URL}, {"tag_name": "v9.0.0", "html_url": 7}])
async def test_odd_json_bodies_are_none(gh, body):
    gh.get(RELEASES_URL).respond(200, json=body)
    assert await check_for_update("0.1.0") is None


async def test_timeout_is_none_and_quick(gh):
    gh.get(RELEASES_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert await check_for_update("0.1.0") is None


async def test_slow_response_is_cut_off_by_the_timeout(gh):
    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json=rel())

    gh.get(RELEASES_URL).mock(side_effect=slow)
    loop = asyncio.get_running_loop()
    start = loop.time()
    assert await check_for_update("0.1.0", timeout=0.2) is None
    assert loop.time() - start < 2


async def test_redirect_loop_and_empty_body_are_none(gh):
    gh.get(RELEASES_URL).respond(200, content=b"")
    assert await check_for_update("0.1.0") is None
    gh.get(RELEASES_URL).respond(301, headers={"location": RELEASES_URL})
    assert await check_for_update("0.1.0") is None


async def test_binary_garbage_body_is_none(gh):
    gh.get(RELEASES_URL).respond(200, content=b"\xff\xfe\x00garbage")
    assert await check_for_update("0.1.0") is None
