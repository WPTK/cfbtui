"""The whole app with a fake client: boot, score, fail, recover, cycle glyphs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from cfbtui.app import CfbApp
from cfbtui.espn.client import EspnNetworkError
from cfbtui.poll import PollIntervals
from cfbtui.ui.widgets.game_card import GameCard
from cfbtui.ui.widgets.score_grid import ScoreGrid, columns_for, sort_key
from cfbtui.ui.widgets.status_bar import StatusBar
from cfbtui.ui.widgets.ticker import Ticker
from tests.fakes import FakeClient, load_board

FAST = PollIntervals(live=0.05, idle=0.05, backoff_max=0.1)
SIZE = (140, 44)


def board(name: str):
    return load_board(f"pairs/{name}.json")


async def wait_for(pilot, predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await pilot.pause(0.02)


async def test_pregame_week_boots_with_kickoff_times_and_an_empty_ticker():
    client = FakeClient(load_board("scoreboard_week7_pregame.json"))
    app = CfbApp(client=client, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        assert len(app.query(GameCard)) == len(load_board("scoreboard_week7_pregame.json").games)
        first = app.query(GameCard).first()
        assert first.model is not None and "ET" in first.model.status
        assert app.query_one(Ticker).entry_count == 0
        status = app.query_one(StatusBar)
        assert "updated" in status.text and "Week 7" in status.text
        assert status.has_class("fresh")


async def test_a_touchdown_flashes_the_card_and_lands_in_the_ticker():
    client = FakeClient(board("touchdown_before"), board("touchdown_after"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(Ticker).entry_count >= 2)
        ticker = app.query_one(Ticker)
        text = " ".join("".join(seg.text for seg in line) for line in ticker.lines)
        assert "KICKOFF" in text, "first sight of a live game announces it"
        assert "TD TEX +7" in text
        card = app.query_one(GameCard)
        assert card.has_class("flash")
        assert card.model.rows[0].score.strip() == "14"


async def test_failure_keeps_the_cards_says_error_and_recovers():
    client = FakeClient(
        board("touchdown_before"),
        EspnNetworkError("cable pulled"),
        EspnNetworkError("cable pulled"),
        board("touchdown_after"),
    )
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        status = app.query_one(StatusBar)
        await wait_for(pilot, lambda: status.has_class("error"))
        assert len(app.query(GameCard)) == 1, "the card stays on screen through the outage"
        assert "ERROR showing data" in status.text
        await wait_for(pilot, lambda: not status.has_class("error"))
        await wait_for(pilot, lambda: app.query_one(GameCard).model.rows[0].score.strip() == "14")
        ticker = app.query_one(Ticker)
        text = " ".join("".join(seg.text for seg in line) for line in ticker.lines)
        assert "TD TEX +7" in text, "the touchdown scored during the outage is reported on recovery"


async def test_failure_before_any_data_says_so_in_the_grid():
    client = FakeClient(EspnNetworkError("dead"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        status = app.query_one(StatusBar)
        await wait_for(pilot, lambda: status.has_class("error"))
        assert "no data yet" in status.text
        message = str(app.query_one("#message").content)
        assert "Could not reach ESPN" in message
        assert len(app.query(GameCard)) == 0


async def test_old_data_dims_the_cards():
    client = FakeClient(board("touchdown_before"), EspnNetworkError("down"))
    app = CfbApp(client=client, intervals=PollIntervals(live=0.05, idle=0.05, backoff_max=0.05), glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(GameCard).has_class("old"))


async def test_g_cycles_glyph_sets_everywhere():
    client = FakeClient(board("touchdown_after"))
    app = CfbApp(client=client, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        card = app.query_one(GameCard)
        assert app.glyphs.name == "ascii" and card.glyphs.name == "ascii"
        await pilot.press("g")
        await pilot.pause()
        assert app.glyphs.name == "unicode"
        assert card.glyphs.name == "unicode"
        assert card.model.status.startswith(app.glyphs.live)
        assert app.query_one(Ticker).glyphs.name == "unicode"
        assert "glyphs: unicode" in app.query_one(StatusBar).text
        for _ in range(3):
            await pilot.press("g")
        await pilot.pause()
        assert app.glyphs.name == "ascii"


async def test_default_glyph_set_is_nerd():
    app = CfbApp(client=FakeClient(board("touchdown_after")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.glyphs.name == "nerd"


async def test_r_polls_right_away():
    client = FakeClient(board("final_after"))
    app = CfbApp(client=client, intervals=PollIntervals(live=30, idle=30), glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: client.scoreboard_calls == 1)
        await pilot.press("r")
        await wait_for(pilot, lambda: client.scoreboard_calls == 2)


async def test_q_quits_and_stops_the_scheduler():
    app = CfbApp(client=FakeClient(board("final_after")), glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("q")
    assert app.scheduler._stopped


async def test_grid_orders_live_then_pregame_then_final_and_stays_stable():
    live = board("touchdown_before").games[0]
    pre = board("game_start_before").games[0]
    fin = board("final_after").games[0]
    from dataclasses import replace

    games = [
        replace(fin, id="3"),
        replace(pre, id="2"),
        replace(live, id="1"),
        replace(pre, id="0", date=pre.date.replace(year=pre.date.year - 1)),
    ]
    ordered = [g.id for g in sorted(games, key=sort_key)]
    assert ordered == ["1", "0", "2", "3"]

    from textual.app import App

    class Host(App[None]):
        def compose(self):
            yield ScoreGrid(id="grid")

    from cfbtui.state.upset import UpsetRule
    from cfbtui.ui import glyphs as g

    async with Host().run_test(size=SIZE) as pilot:
        grid = pilot.app.query_one(ScoreGrid)
        rule = UpsetRule()
        grid.update_games(games, g.get("ascii"), rule)
        await pilot.pause()
        await pilot.pause()
        assert [c.game_id for c in grid.cards] == ordered
        # Same games again in a different feed order: nothing moves.
        grid.update_games(list(reversed(games)), g.get("ascii"), rule)
        await pilot.pause()
        await pilot.pause()
        assert [c.game_id for c in grid.cards] == ordered
        # The pregame game kicks off and jumps to the live group; a vanished game's card goes away.
        started = replace(live, id="2", date=pre.date)
        grid.update_games([games[0], started, games[2]], g.get("ascii"), rule)
        await pilot.pause()
        await pilot.pause()
        assert [c.game_id for c in grid.cards] == ["1", "2", "3"], "both live now; same kickoff, so id order"


def test_columns_reflow_with_width():
    assert columns_for(20) == 1
    assert columns_for(36) == 1
    assert columns_for(72) == 2
    assert columns_for(140) == 3
