"""Clicking or choosing a ticker line locates its game: scroll to it, focus it, pulse it."""
from __future__ import annotations

import pytest

from cfbtui.app import CfbApp
from cfbtui.state.events import GameStarted
from cfbtui.ui.widgets.game_card import GameCard
from cfbtui.ui.widgets.score_grid import ScoreGrid
from cfbtui.ui.widgets.ticker import Ticker, TickerLine
from tests.fakes import FakeClient, load_board
from tests.test_app_smoke import FAST, wait_for

SIZE = (60, 40)


def _app() -> CfbApp:
    return CfbApp(client=FakeClient(load_board("scoreboard_week7_pregame.json")), intervals=FAST, glyph_set="ascii")


async def _boot(app: CfbApp, pilot) -> list:
    await wait_for(pilot, lambda: len(app.query(GameCard)) > 3)
    games = list(app.store.games)
    app.query_one(Ticker).add_events([GameStarted(g) for g in games])
    ticker = app.query_one(Ticker)
    await wait_for(pilot, lambda: ticker.scroll_y == ticker.max_scroll_y > 0)  # auto-scrolled to the newest line
    return games


def _in_view(ticker: Ticker, line: TickerLine) -> bool:
    return ticker.region.y <= line.region.y < ticker.region.bottom


async def _click(pilot, ticker: Ticker, line: TickerLine, **kwargs) -> None:
    """Scroll ``line`` into view, wait for the ticker to settle there, then click it."""
    line.scroll_visible(animate=False)
    await wait_for(pilot, lambda: _in_view(ticker, line))
    await pilot.click(line, **kwargs)


def _located(app: CfbApp, game_id: str) -> bool:
    card = app.query_one(ScoreGrid).card_for(game_id)
    return card is not None and app.focused is card and card.has_class("pulse-locate")


@pytest.mark.parametrize("layout", ["grid", "list"])
async def test_clicking_the_first_and_last_line_locates_their_games(layout):
    app = _app()
    async with app.run_test(size=SIZE) as pilot:
        games = await _boot(app, pilot)
        if layout == "list":
            await pilot.press("v")
            await pilot.pause()
        ticker = app.query_one(Ticker)
        await _click(pilot, ticker, ticker.lines[0])
        await wait_for(pilot, lambda: _located(app, games[0].id))
        await _click(pilot, ticker, ticker.lines[-1])
        await wait_for(pilot, lambda: _located(app, games[-1].id))


async def test_clicking_the_second_row_of_a_wrapped_line_locates_its_game():
    app = _app()
    async with app.run_test(size=(40, 40)) as pilot:
        games = await _boot(app, pilot)
        ticker = app.query_one(Ticker)
        line = ticker.lines[1]
        assert line.size.height > 1, "the line wraps at this width"
        await _click(pilot, ticker, line, offset=(3, line.size.height - 1))
        await wait_for(pilot, lambda: _located(app, games[1].id))


async def test_enter_on_a_focused_line_and_up_down_between_lines():
    app = _app()
    async with app.run_test(size=SIZE) as pilot:
        games = await _boot(app, pilot)
        ticker = app.query_one(Ticker)
        ticker.lines[0].focus()
        await pilot.press("down")
        assert app.focused is ticker.lines[1]
        await pilot.press("up", "up")
        assert app.focused is ticker.lines[0], "stops at the first line"
        await pilot.press("down", "enter")
        await wait_for(pilot, lambda: _located(app, games[1].id))


async def test_a_game_hidden_by_the_filter_is_shown_with_a_toast_naming_the_filter():
    app = _app()
    async with app.run_test(size=SIZE) as pilot:
        games = await _boot(app, pilot)
        app.filter = "live"
        app._repaint_grid()
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 0)
        ticker = app.query_one(Ticker)
        await _click(pilot, ticker, ticker.lines[0])
        await wait_for(pilot, lambda: _located(app, games[0].id))
        assert app.filter == "all"
        assert any("hidden by the Live filter" in n.message for n in app._notifications)


async def test_a_game_hidden_by_the_conference_is_shown_and_the_conference_cleared():
    app = _app()
    async with app.run_test(size=SIZE) as pilot:
        games = await _boot(app, pilot)
        app.conference = "no-such-conference"
        app._repaint_grid()
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 0)
        ticker = app.query_one(Ticker)
        await _click(pilot, ticker, ticker.lines[0])
        await wait_for(pilot, lambda: _located(app, games[0].id))
        assert app.conference is None
        assert any("hidden by the Conference no-such-conference conference" in n.message for n in app._notifications)


async def test_a_line_for_a_game_that_left_the_board_says_so():
    app = _app()
    async with app.run_test(size=SIZE) as pilot:
        await _boot(app, pilot)
        gone = load_board("pairs/final_after.json").games[0]
        assert gone.id not in app.store
        ticker = app.query_one(Ticker)
        ticker.add_events([GameStarted(gone)])
        await _click(pilot, ticker, ticker.lines[-1])
        await wait_for(pilot, lambda: any("no longer on the board" in n.message for n in app._notifications))
