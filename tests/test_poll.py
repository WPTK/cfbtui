"""PollScheduler and Freshness, driven by a fake client and a fake clock."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cfbtui.espn.client import EspnHttpError, EspnNetworkError
from cfbtui.espn.models import Scoreboard
from cfbtui.poll import (
    STALE_FACTOR,
    Freshness,
    FreshnessState,
    PollIntervals,
    PollScheduler,
    format_age,
)
from cfbtui.state.events import GameStarted, Scored
from cfbtui.state.store import GameStore
from tests.fakes import FakeClient, FakeClock, load_board, load_rankings

LIVE, IDLE = 20.0, 300.0


def board(name: str) -> Scoreboard:
    return load_board(f"pairs/{name}.json")


def make(client: FakeClient, clock: FakeClock | None = None, **kw) -> tuple[PollScheduler, FakeClock, list]:
    clock = clock or FakeClock()
    results: list = []
    sched = PollScheduler(
        client,
        GameStore(),
        intervals=PollIntervals(live=LIVE, idle=IDLE, backoff_max=120.0),
        clock=clock,
        now=clock.now,
        on_result=results.append,
        **kw,
    )
    return sched, clock, results


# --- first poll ------------------------------------------------------------------


def test_an_empty_store_passed_in_is_the_store_used():
    """GameStore defines __len__, so an empty one is falsy; ``store or X`` once swapped it out."""
    store = GameStore()
    sched = PollScheduler(FakeClient(), store)
    assert sched.store is store


async def test_first_poll_applies_games_and_reports_fresh():
    client = FakeClient(board("touchdown_before"))
    sched, _clock, results = make(client)
    assert sched.freshness().state is FreshnessState.LOADING
    result = await sched.poll_once()
    assert result.ok and result.scoreboard is not None
    assert len(sched.store) == 1
    assert result.freshness.state is FreshnessState.FRESH
    assert result.freshness.age == 0
    assert results == [result]
    # A live game on first sight announces itself (store policy), nothing else.
    assert [type(e) for e in result.events] == [GameStarted]


async def test_first_poll_passes_week_and_group_to_the_client():
    client = FakeClient(board("touchdown_before"))
    sched, _, _ = make(client, week=7, group=81)
    await sched.poll_once()
    assert client.kwargs == [{"week": 7, "group": 81}]


async def test_rankings_load_once_and_reach_the_rule():
    rankings = load_rankings()
    client = FakeClient(board("touchdown_before"), rankings=rankings)
    sched, _, _ = make(client)
    await sched.poll_once()
    await sched.poll_once()
    assert client.rankings_calls == 1
    assert sched.store.rule.ranking is not None


async def test_rankings_failure_is_quiet_and_retried_later():
    client = FakeClient(board("touchdown_before"), rankings=EspnNetworkError("down"))
    sched, clock, _ = make(client)
    result = await sched.poll_once()
    assert result.ok and result.freshness.state is FreshnessState.FRESH
    assert client.rankings_calls == 1
    await sched.poll_once()
    assert client.rankings_calls == 1, "not retried inside the retry window"
    clock.advance(301)
    await sched.poll_once()
    assert client.rankings_calls == 2


# --- a scoring tick ----------------------------------------------------------------


async def test_scoring_tick_emits_a_scored_event():
    client = FakeClient(board("touchdown_before"), board("touchdown_after"))
    sched, clock, _results = make(client)
    await sched.poll_once()
    clock.advance(20)
    result = await sched.poll_once()
    scored = [e for e in result.events if isinstance(e, Scored)]
    assert len(scored) == 1 and scored[0].points == 7
    games = sched.store.games
    assert games[0].home.score + games[0].away.score == 21


# --- errors, stale data, recovery ---------------------------------------------------


async def test_error_keeps_last_data_and_marks_error():
    client = FakeClient(board("touchdown_after"), EspnHttpError(503, "http://x"))
    sched, clock, _results = make(client)
    await sched.poll_once()
    clock.advance(20)
    result = await sched.poll_once()
    assert not result.ok and result.scoreboard is None and result.events == ()
    assert isinstance(result.error, EspnHttpError)
    assert len(sched.store) == 1, "the last good games stay in the store"
    assert sched.scoreboard is not None
    f = result.freshness
    assert f.state is FreshnessState.ERROR
    assert f.failures == 1
    assert f.age == 20
    assert not f.data_old, "one failed poll is not yet old data"
    assert "503" in (f.error or "")


async def test_data_goes_old_as_time_passes_without_a_good_poll():
    client = FakeClient(board("touchdown_after"), EspnNetworkError("down"))
    sched, clock, _ = make(client)
    await sched.poll_once()
    await sched.poll_once()
    clock.advance(STALE_FACTOR * LIVE + 1)
    f = sched.freshness()
    assert f.state is FreshnessState.ERROR and f.data_old


async def test_failure_before_any_data_is_an_error_with_no_age():
    client = FakeClient(EspnNetworkError("down"))
    sched, _, _ = make(client)
    result = await sched.poll_once()
    f = result.freshness
    assert f.state is FreshnessState.ERROR and f.age is None and not f.data_old
    assert sched.scoreboard is None


async def test_recovery_clears_the_error_and_diffs_against_the_old_data():
    client = FakeClient(
        board("touchdown_before"),
        EspnNetworkError("down"),
        EspnNetworkError("down"),
        board("touchdown_after"),
    )
    sched, clock, _ = make(client)
    await sched.poll_once()
    for _ in range(2):
        clock.advance(20)
        assert not (await sched.poll_once()).ok
    assert sched.freshness().failures == 2
    clock.advance(40)
    result = await sched.poll_once()
    assert result.ok
    assert result.freshness.state is FreshnessState.FRESH
    assert result.freshness.failures == 0 and result.freshness.error is None
    # The touchdown that happened during the outage is still reported.
    assert any(isinstance(e, Scored) for e in result.events)


async def test_unexpected_exception_does_not_kill_the_loop():
    client = FakeClient(ValueError("parser bug"), board("touchdown_before"))
    sched, _, _ = make(client)
    assert not (await sched.poll_once()).ok
    assert (await sched.poll_once()).ok


async def test_scheduler_falling_behind_is_stale_not_error():
    client = FakeClient(board("touchdown_before"))
    sched, clock, _ = make(client)
    await sched.poll_once()
    clock.advance(STALE_FACTOR * LIVE + 1)  # the laptop slept; no poll failed
    f = sched.freshness()
    assert f.state is FreshnessState.STALE and f.data_old and f.failures == 0


# --- "no change" is not "no data" ----------------------------------------------------


async def test_a_long_halftime_with_identical_polls_stays_fresh():
    half = board("halftime_after")
    client = FakeClient(half)
    sched, clock, _ = make(client)
    await sched.poll_once()
    for _ in range(30):  # ten minutes of nothing happening
        clock.advance(LIVE)
        result = await sched.poll_once()
        assert result.ok and result.events == ()
        assert result.freshness.state is FreshnessState.FRESH
        assert not result.freshness.data_old
    clock.advance(10)
    assert sched.freshness().state is FreshnessState.FRESH


# --- intervals -----------------------------------------------------------------------


AWAY = 10_000.0  # seconds without input, well past away_after


class Presence:
    """A stand-in for the machine's input timer. Flip ``away`` to walk off or come back."""

    def __init__(self, away: bool = False) -> None:
        self.away = away

    def __call__(self) -> float:
        return AWAY if self.away else 0.0


async def test_someone_at_the_computer_polls_fast_whatever_the_games_are_doing():
    for name in ("touchdown_before", "final_after", "game_start_before"):
        sched, _, _ = make(FakeClient(board(name)))
        await sched.poll_once()
        assert sched.next_delay() == LIVE and not sched.away
        assert sched.freshness().stale_after == STALE_FACTOR * LIVE


async def test_nobody_at_the_computer_polls_slowly_even_with_games_live():
    for name in ("touchdown_before", "final_after"):
        sched, _, _ = make(FakeClient(board(name)), idle_for=Presence(away=True))
        await sched.poll_once()
        assert sched.next_delay() == IDLE and sched.away
        assert sched.freshness().stale_after == STALE_FACTOR * IDLE


async def test_unknown_presence_counts_as_present():
    sched, _, _ = make(FakeClient(board("final_after")), idle_for=lambda: None)
    await sched.poll_once()
    assert sched.next_delay() == LIVE and not sched.away


async def test_away_starts_at_the_configured_number_of_seconds():
    here, _, _ = make(FakeClient(board("final_after")), idle_for=lambda: 299.0)
    gone, _, _ = make(FakeClient(board("final_after")), idle_for=lambda: 300.0)
    await here.poll_once()
    await gone.poll_once()
    assert here.next_delay() == LIVE
    assert gone.next_delay() == IDLE


async def test_interval_follows_the_user_leaving_and_coming_back():
    presence = Presence()
    sched, _, _ = make(FakeClient(board("final_after")), idle_for=presence)
    await sched.poll_once()
    assert sched.next_delay() == LIVE
    presence.away = True
    await sched.poll_once()
    assert sched.next_delay() == IDLE
    presence.away = False
    await sched.poll_once()
    assert sched.next_delay() == LIVE


async def test_observing_a_departure_marks_away_without_polling():
    presence = Presence()
    sched, _, results = make(FakeClient(board("final_after")), idle_for=presence)
    await sched.poll_once()
    presence.away = True
    sched.observe_presence()
    sched.observe_presence()
    assert sched.away and len(results) == 1


def _pregame_at(offset: timedelta) -> tuple[Scoreboard, FakeClock]:
    pre = board("game_start_before")
    game = pre.games[0]
    clock = FakeClock(start=game.date - offset)
    return pre, clock


async def test_away_poll_is_pulled_forward_to_a_nearby_kickoff():
    pre, clock = _pregame_at(timedelta(seconds=100))
    sched, _, _ = make(FakeClient(pre), clock, idle_for=Presence(away=True))
    await sched.poll_once()
    assert sched.next_delay() == pytest.approx(100)


async def test_kickoff_beyond_the_idle_window_does_not_shorten_the_wait():
    pre, clock = _pregame_at(timedelta(hours=2))
    sched, _, _ = make(FakeClient(pre), clock, idle_for=Presence(away=True))
    await sched.poll_once()
    assert sched.next_delay() == IDLE


async def test_a_kickoff_that_has_passed_does_not_wake_an_away_board():
    pre, clock = _pregame_at(timedelta(seconds=-120))  # kickoff was two minutes ago, ESPN still says scheduled
    sched, _, _ = make(FakeClient(pre), clock, idle_for=Presence(away=True))
    await sched.poll_once()
    assert sched.next_delay() == IDLE


async def test_error_backoff_doubles_to_a_cap_and_never_beats_the_normal_interval():
    client = FakeClient(board("touchdown_before"), EspnNetworkError("down"))
    sched, clock, _ = make(client)
    await sched.poll_once()
    seen = []
    for _ in range(5):
        clock.advance(20)
        await sched.poll_once()
        seen.append(sched.next_delay())
    assert seen == [40, 80, 120, 120, 120]


async def test_idle_error_backoff_is_not_faster_than_idle():
    client = FakeClient(board("final_after"), EspnNetworkError("down"))
    sched, _, _ = make(client, idle_for=Presence(away=True))
    await sched.poll_once()
    await sched.poll_once()
    assert sched.next_delay() == IDLE


async def test_countdown_tracks_the_clock_and_is_none_while_fetching():
    sched, clock, _ = make(FakeClient(board("touchdown_before")))
    assert sched.seconds_until_next() is None
    await sched.poll_once()
    assert sched.seconds_until_next() == LIVE
    clock.advance(7)
    assert sched.seconds_until_next() == 13
    clock.advance(100)
    assert sched.seconds_until_next() == 0


# --- the run loop --------------------------------------------------------------------


async def _until(condition, *, timeout: float = 5.0) -> None:
    """Poll ``condition`` until it holds. Generous timeout: a loaded machine must not fail these."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the scheduler")
        await asyncio.sleep(0.01)


async def test_run_loop_polls_repeatedly_and_stops():
    client = FakeClient(board("final_after"))
    results: list = []
    sched = PollScheduler(
        client,
        GameStore(),
        intervals=PollIntervals(live=0.01, idle=0.01, backoff_max=0.02),
        on_result=results.append,
    )
    task = asyncio.create_task(sched.run())
    await _until(lambda: len(results) >= 3)
    sched.stop()
    await asyncio.wait_for(task, timeout=5)
    assert len(results) >= 3


async def test_refresh_wakes_the_loop_early():
    client = FakeClient(board("final_after"))
    results: list = []
    sched = PollScheduler(
        client,
        GameStore(),
        intervals=PollIntervals(live=30, idle=30),
        on_result=results.append,
    )
    task = asyncio.create_task(sched.run())
    await _until(lambda: len(results) == 1)
    sched.refresh()
    await _until(lambda: len(results) == 2)
    sched.stop()
    await asyncio.wait_for(task, timeout=5)


async def test_coming_back_to_the_computer_wakes_the_loop():
    presence = Presence(away=True)
    results: list = []
    sched = PollScheduler(
        FakeClient(board("final_after")),
        GameStore(),
        intervals=PollIntervals(live=30, idle=30),
        on_result=results.append,
        idle_for=presence,
    )
    task = asyncio.create_task(sched.run())
    await _until(lambda: len(results) == 1)
    assert sched.away
    sched.observe_presence()  # still away: nothing happens
    await asyncio.sleep(0.05)
    assert len(results) == 1
    presence.away = False
    sched.observe_presence()
    await _until(lambda: len(results) == 2)
    assert not sched.away
    sched.stop()
    await asyncio.wait_for(task, timeout=5)


async def test_switch_resets_the_store_and_drops_an_in_flight_old_board():
    gate = asyncio.Event()

    class SlowClient(FakeClient):
        async def scoreboard(self, *, week=None, group=80):
            await gate.wait()
            return await super().scoreboard(week=week, group=group)

    client = SlowClient(board("touchdown_before"))
    sched, _, results = make(client)
    task = asyncio.create_task(sched.poll_once())
    await asyncio.sleep(0)
    sched.switch(week=8)
    gate.set()
    await task
    assert results == [], "the old week's board is discarded, not reported"
    assert len(sched.store) == 0
    assert sched.week == 8


def test_format_age():
    assert format_age(None) == "--"
    assert format_age(0) == "0s"
    assert format_age(12.9) == "12s"
    assert format_age(185) == "3m05s"
    assert format_age(7500) == "2h05m"


def test_freshness_data_old_needs_an_age():
    assert not Freshness().data_old
    assert Freshness(FreshnessState.ERROR, age=100, stale_after=50).data_old
    assert not Freshness(FreshnessState.ERROR, age=10, stale_after=50).data_old


async def test_failure_of_an_old_week_fetch_after_switch_is_not_counted():
    gate = asyncio.Event()

    class FailingSlow(FakeClient):
        async def scoreboard(self, *, week=None, group=80):
            await gate.wait()
            raise EspnNetworkError("old week died")

    sched, _, results = make(FailingSlow())
    task = asyncio.create_task(sched.poll_once())
    await asyncio.sleep(0)
    sched.switch(week=8)
    gate.set()
    await task
    assert results == [] and sched.freshness().failures == 0
