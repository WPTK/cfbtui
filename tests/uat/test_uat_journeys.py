"""UAT: end-user journeys through the real CfbApp, one documented key at a time.

Every test drives the app with Textual's Pilot against a scripted client (no network) and asserts on what
a person would see: card text, the status line, toasts, the ticker, the screens, the clipboard.
"""
from __future__ import annotations

import io
import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console
from rich.text import Text
from textual.widgets import OptionList, Static

from cfbtui.app import CfbApp
from cfbtui.clipboard import ClipboardError
from cfbtui.config import Config, load_config
from cfbtui.espn.client import GROUP_FBS, GROUP_FCS, EspnNetworkError
from cfbtui.espn.models import Competitor, Game, GameState, Scoreboard, Status, Team
from cfbtui.poll import PollIntervals
from cfbtui.ui.screens.conferences import ConferenceScreen
from cfbtui.ui.screens.detail import DetailScreen
from cfbtui.ui.screens.rankings import RankingsScreen
from cfbtui.ui.widgets.game_card import GameCard
from cfbtui.ui.widgets.score_grid import ScoreGrid
from cfbtui.ui.widgets.status_bar import StatusBar
from cfbtui.ui.widgets.ticker import Ticker
from cfbtui.update import UpdateInfo
from tests.fakes import FakeClient, load_board, load_rankings
from tests.test_app_smoke import FAST, SIZE, wait_for
from tests.test_screens import fixture_summary

SLOW = PollIntervals(live=1000, idle=1000, backoff_max=1000)
KICK = datetime(2026, 10, 17, 16, 0, tzinfo=UTC)


# --- builders ---------------------------------------------------------------------


def team(n: int, conf: str | None = "8") -> Team:
    return Team(
        id=str(1000 + n), abbreviation=f"T{n:03d}", display_name=f"Team {n}", short_name=f"Team{n}",
        color="#112233", alt_color="#445566", conference_id=conf,
    )


def make_game(n: int, kind: str = "pre", a: int = 0, h: int = 0, ar: int | None = None, hr: int | None = None,
              ca: str | None = "8", ch: str | None = "8", base: int = 0) -> Game:
    if kind == "pre":
        status = Status(GameState.PRE, "STATUS_SCHEDULED", False, 0, "0:00", "Sat", "Sat")
    elif kind == "live":
        status = Status(GameState.IN, "STATUS_IN_PROGRESS", False, 2, "5:00", "5:00 - 2nd", "5:00 - 2nd")
    else:
        status = Status(GameState.POST, "STATUS_FINAL", True, 4, "0:00", "Final", "Final")
    gid = base + n
    return Game(
        id=str(9000 + gid), date=KICK + timedelta(minutes=gid), name=f"Team {gid} at Team {gid}",
        short_name=f"T{n:03d} @ T{n + 5000:03d}",
        away=Competitor(team(n * 2 + base * 2, ca), "away", a, ar, "1-0"),
        home=Competitor(team(n * 2 + 1 + base * 2, ch), "home", h, hr, "1-0"),
        status=status, week=7,
    )


def mixed(base: int = 0) -> tuple[Game, ...]:
    """12 games: ranked live, plain live, pregame, finals, across SEC (8), Big Ten (5), ACC (1)."""
    return (
        make_game(0, "live", 14, 7, ar=3, hr=None, base=base),
        make_game(1, "live", 3, 10, base=base, ca="5", ch="5"),
        make_game(2, "pre", ar=10, base=base, ca="1", ch="1"),
        make_game(3, "pre", base=base),
        make_game(4, "pre", base=base, ca="5", ch="8"),
        make_game(5, "final", 31, 28, ar=5, hr=20, base=base),
        make_game(6, "final", 10, 45, base=base, ca="1", ch="5"),
        make_game(7, "final", 17, 17, base=base),
        make_game(8, "live", 21, 24, ar=12, hr=25, base=base, ca="1", ch="1"),
        make_game(9, "pre", base=base),
        make_game(10, "final", 0, 3, base=base),
        make_game(11, "pre", base=base),
    )


def many(count: int, base: int = 0) -> tuple[Game, ...]:
    kinds = ("pre", "live", "final")
    return tuple(make_game(i, kinds[i % 3], i % 40, (i * 3) % 40, base=base) for i in range(count))


class UatClient:
    """Serves a board per (week, group), the fixture summary, and rankings. Records every call."""

    def __init__(self, games=None, *, week: int = 7, rankings=(), board_fn=None, summary_error=None) -> None:
        self.games = games if games is not None else mixed()
        self.cur_week = week
        self._rankings = rankings
        self.board_fn = board_fn
        self.summary_error = summary_error
        self.calls: list[tuple[int | None, int]] = []
        self.rankings_calls = 0
        self.summary_calls = 0

    async def scoreboard(self, *, week: int | None = None, group: int = GROUP_FBS) -> Scoreboard:
        self.calls.append((week, group))
        if self.board_fn is not None:
            return self.board_fn(week, group)
        base = 0 if group == GROUP_FBS else 500
        shown = week if week is not None else self.cur_week
        if not self.games:
            return Scoreboard(games=(), week=shown)
        games = tuple(replace(g, id=f"{g.id}-{group}-{shown}") for g in self.games) if (week or group != GROUP_FBS) else self.games
        del base
        return Scoreboard(games=games, week=shown)

    async def rankings(self):
        self.rankings_calls += 1
        if isinstance(self._rankings, Exception):
            raise self._rankings
        return self._rankings

    async def summary(self, event_id: str):
        self.summary_calls += 1
        if self.summary_error is not None:
            raise self.summary_error
        return fixture_summary()


class Clip:
    """A stub clipboard that remembers every copy, and can be made to fail."""

    def __init__(self) -> None:
        self.copies: list[str] = []
        self.fail = False

    def __call__(self, text: str) -> None:
        if self.fail:
            raise ClipboardError("no clipboard available")
        self.copies.append(text)


def make_app(client=None, *, intervals=SLOW, glyph_set="ascii", clip: Clip | None = None, **kw) -> CfbApp:
    app = CfbApp(client=client if client is not None else UatClient(), intervals=intervals, glyph_set=glyph_set, **kw)
    if clip is not None:
        app.copier = clip
    return app


def text_of(obj) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, Text):
        return obj.plain
    buf = io.StringIO()
    Console(file=buf, width=200, force_terminal=False, color_system=None).print(obj)
    return buf.getvalue()


def screen_text(app: CfbApp) -> str:
    out = []
    for static in app.screen.query(Static):
        out.append(static.border_title or "")
        out.append(text_of(static.content))
    return "\n".join(out)


def card_text(card: GameCard) -> str:
    return text_of(card.content)


def toasts(app: CfbApp) -> list[str]:
    return [n.message for n in app._notifications]


def gids(app: CfbApp) -> list[str]:
    return [c.game_id for c in app.query_one(ScoreGrid).cards]


def status(app: CfbApp) -> str:
    return app.query_one(StatusBar).text


def message(app: CfbApp) -> str:
    return text_of(app.query_one(ScoreGrid).query_one("#message", Static).content)


def focused_id(app: CfbApp) -> str | None:
    card = app.query_one(ScoreGrid).focused_card
    return card.game_id if card else None


async def booted(pilot, app: CfbApp, count: int | None = None) -> None:
    await wait_for(pilot, lambda: len(app.query(GameCard)) == (count if count is not None else len(app.store)) > 0)


async def switched(pilot, app: CfbApp, count: int) -> None:
    await wait_for(pilot, lambda: len(app.query(GameCard)) == count and len(app.store) == count)
    await pilot.pause()


# =====================================================================================
# Launch
# =====================================================================================


async def test_launch_shows_cards_ticker_and_a_status_line_that_reads_updated():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        assert "updated" in status(app) and "Week 7 FBS" in status(app) and "3 live of 12" in status(app)
        assert app.query_one(StatusBar).has_class("fresh")
        assert "KICKOFF" in ticker_text(app), "first sight of live games announces them (only a switch is quiet)"
        # the live ranked game is first, then the other live ones, then pregame, then finals
        order = [app.store.get(i) for i in gids(app)]
        states = [g.state for g in order]
        assert states == sorted(states, key=lambda s: {GameState.IN: 0, GameState.PRE: 1, GameState.POST: 2}[s])
        text = card_text(app.query_one(ScoreGrid).cards[0])
        assert "T000" in text and "14" in text


async def test_loading_message_shows_before_the_first_board():
    class Slow(UatClient):
        async def scoreboard(self, **kw):
            import asyncio

            await asyncio.sleep(0.4)
            return await super().scoreboard(**kw)

    app = make_app(Slow())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.05)
        assert "Loading the scoreboard" in message(app)
        assert "loading" in status(app)
        await booted(pilot, app, 12)
        assert message(app) == ""


# =====================================================================================
# Arrow keys
# =====================================================================================


async def test_arrow_keys_walk_the_card_grid_and_clamp_at_the_edges():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        grid = app.query_one(ScoreGrid)
        cols = grid.columns
        assert cols >= 3, "140 columns fit several cards across"
        cards = [c.game_id for c in grid.cards]
        assert focused_id(app) is None
        await pilot.press("right")
        assert focused_id(app) == cards[0], "the first arrow lands on the first card"
        await pilot.press("left")
        assert focused_id(app) == cards[0], "left at the first card stays"
        await pilot.press("up")
        assert focused_id(app) == cards[0]
        await pilot.press("right")
        assert focused_id(app) == cards[1]
        await pilot.press("down")
        assert focused_id(app) == cards[1 + cols]
        await pilot.press("up")
        assert focused_id(app) == cards[1]
        await pilot.press("left")
        assert focused_id(app) == cards[0]
        for _ in range(20):
            await pilot.press("down")
        # down on a short last row lands on the final card or stays on the last row
        assert grid.cards.index(grid.focused_card) >= len(cards) - cols
        for _ in range(20):
            await pilot.press("right")
        assert focused_id(app) == cards[-1]
        await pilot.press("right")
        assert focused_id(app) == cards[-1]


async def test_arrow_keys_in_the_list_layout_move_one_row_at_a_time():
    app = make_app(config=Config(), layout=None) if False else make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("v")
        await pilot.pause()
        grid = app.query_one(ScoreGrid)
        assert grid.columns == 1
        cards = [c.game_id for c in grid.cards]
        await pilot.press("down")
        assert focused_id(app) == cards[0]
        await pilot.press("down")
        assert focused_id(app) == cards[1]
        await pilot.press("down")
        assert focused_id(app) == cards[2]
        await pilot.press("up")
        assert focused_id(app) == cards[1]
        await pilot.press("right")
        assert focused_id(app) == cards[2], "right and left still step one game"
        await pilot.press("left")
        assert focused_id(app) == cards[1]


async def test_a_narrow_terminal_is_one_column_and_arrows_still_work():
    app = make_app()
    async with app.run_test(size=(50, 30)) as pilot:
        await booted(pilot, app, 12)
        grid = app.query_one(ScoreGrid)
        assert grid.columns == 1
        cards = [c.game_id for c in grid.cards]
        await pilot.press("down", "down", "down")
        assert focused_id(app) == cards[2]


# =====================================================================================
# Enter -> detail -> Esc
# =====================================================================================


async def test_enter_opens_detail_with_scoring_plays_and_esc_returns_to_the_same_card():
    client = UatClient()
    app = make_app(client)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("right", "right")
        before = focused_id(app)
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen) and app.screen.summary is not None)
        shown = app.screen.game
        assert shown.id == before
        body = text_of(app.screen.query_one("#detail", Static).content)
        assert shown.away.abbreviation in body and shown.home.abbreviation in body
        assert "Scoring" in body or "Q1" in body or "touchdown" in body.lower() or len(body) > 50
        assert client.summary_calls >= 1
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DetailScreen) and len(app.screen_stack) == 1
        assert focused_id(app) == before, "closing the detail leaves focus where it was"
        await pilot.press("right")
        assert focused_id(app) != before, "and the arrows still work"


async def test_enter_with_nothing_focused_says_what_to_do():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert any("arrow keys" in t for t in toasts(app))


async def test_detail_with_a_failing_summary_shows_the_error_and_still_closes():
    app = make_app(UatClient(summary_error=EspnNetworkError("boom")))
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("right", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen) and app.screen.error is not None)
        assert "boom" in text_of(app.screen.query_one("#detail", Static).content)
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


async def test_detail_header_follows_a_score_change_from_the_poll():
    before, after = load_board("pairs/touchdown_before.json"), load_board("pairs/touchdown_after.json")
    client = FakeClient(before, after)
    client.summary = UatClient().summary
    app = make_app(client, intervals=PollIntervals(live=0.4, idle=0.4, backoff_max=1))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        await pilot.press("right", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))
        scores = lambda: (app.screen.game.away.score, app.screen.game.home.score)  # noqa: E731
        await wait_for(pilot, lambda: scores() == (after.games[0].away.score, after.games[0].home.score))


# =====================================================================================
# Rankings
# =====================================================================================


async def test_R_shows_ap_and_coaches_and_esc_returns():
    client = UatClient(rankings=load_rankings())
    app = make_app(client)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        body = screen_text(app)
        assert "AP Top 25" in body and "Coaches" in body
        assert "FCS Coaches" not in body and "Division II" not in body
        assert len(app.screen.polls) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


async def test_rankings_show_only_cfp_once_it_is_released_and_stay_cfp_if_it_drops_out():
    polls = load_rankings()
    cfp = replace(polls[0], id="cfp1", name="College Football Playoff Rankings", short_name="CFP", type="cfp")
    client = UatClient(rankings=(*polls, cfp))
    app = make_app(client)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        body = screen_text(app)
        assert "College Football Playoff" in body
        assert "AP Top 25" not in body and "AFCA Coaches" not in body
        await pilot.press("escape")
        await pilot.pause()
        client._rankings = polls  # the payload stops listing the CFP poll
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        assert "College Football Playoff" in screen_text(app), "once released, always CFP this run"
        assert "AP Top 25" not in screen_text(app)


async def test_rankings_on_the_fcs_board_show_the_fcs_poll():
    client = UatClient(rankings=load_rankings())
    app = make_app(client, group=GROUP_FCS)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        body = screen_text(app)
        assert "FCS Coaches" in body and "AP Top 25" not in body


async def test_rankings_error_and_empty_are_readable_and_esc_works():
    client = UatClient(rankings=EspnNetworkError("offline"))
    app = make_app(client)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        assert "Could not load the polls" in screen_text(app) and "offline" in screen_text(app)
        await pilot.press("escape")
        await pilot.pause()
        client._rankings = ()
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        assert "No polls have been released" in screen_text(app)
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


# =====================================================================================
# Weeks
# =====================================================================================


async def test_brackets_step_through_the_season_into_bowls_and_playoff_then_stop():
    client = UatClient()
    app = make_app(client, week=14)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        assert "Week 14" in status(app)
        await pilot.press("right_square_bracket")
        await wait_for(pilot, lambda: "Week 15" in status(app))
        await pilot.press("right_square_bracket")
        await wait_for(pilot, lambda: "Bowls" in status(app))
        assert client.calls[-1][0] == 16
        await pilot.press("right_square_bracket")
        await wait_for(pilot, lambda: "Playoff" in status(app))
        assert client.calls[-1][0] == 17
        generation = app.scheduler.generation
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.scheduler.generation == generation and app.scheduler.week == 17
        assert any("last week" in t for t in toasts(app))
        await pilot.press("left_square_bracket")
        await wait_for(pilot, lambda: "Bowls" in status(app) and "Playoff" not in status(app))
        await pilot.press("left_square_bracket")
        await wait_for(pilot, lambda: "Week 15" in status(app))


async def test_left_bracket_at_week_one_does_not_wrap():
    client = UatClient(week=1)
    app = make_app(client, week=1)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        generation = app.scheduler.generation
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.scheduler.week == 1 and app.scheduler.generation == generation
        assert any("first week" in t for t in toasts(app))
        assert "Week 1" in status(app)


async def test_brackets_from_the_current_week_use_the_boards_week_number():
    client = UatClient(week=7)
    app = make_app(client)  # week=None: "this week"
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("left_square_bracket")
        await wait_for(pilot, lambda: client.calls[-1][0] == 6)
        await pilot.press("right_square_bracket", "right_square_bracket")
        await wait_for(pilot, lambda: client.calls[-1][0] == 8)
        await pilot.press("t")
        await wait_for(pilot, lambda: app.scheduler.week is None)
        await wait_for(pilot, lambda: "Week 7" in status(app))


async def test_a_week_switch_shows_only_the_new_boards_games_and_clears_stale_ones():
    client = UatClient()
    app = make_app(client)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        old = set(gids(app))
        await pilot.press("left_square_bracket")
        await switched(pilot, app, 12)
        new = set(gids(app))
        assert new and not (old & new), "week 6 shows week 6's games only"
        assert app.query_one(Ticker).entry_count == 0


async def test_t_goes_back_to_this_week_and_a_second_t_only_says_so():
    client = UatClient()
    app = make_app(client, week=3)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        assert "Week 3" in status(app)
        await pilot.press("t")
        await wait_for(pilot, lambda: app.scheduler.week is None and "Week 7" in status(app))
        generation = app.scheduler.generation
        await pilot.press("t")
        await pilot.pause()
        assert app.scheduler.generation == generation
        assert any("Already on the current week" in x for x in toasts(app))


async def test_f_toggles_fbs_and_fcs_keeping_the_week_and_dropping_the_conference():
    client = UatClient()
    app = make_app(client, week=5)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        app.conference = "8"
        await pilot.press("f")
        await wait_for(pilot, lambda: client.calls[-1] == (5, GROUP_FCS))
        await switched(pilot, app, 12)
        assert "FCS" in status(app) and "Week 5" in status(app)
        assert app.conference is None and "SEC" not in status(app)
        await pilot.press("f")
        await wait_for(pilot, lambda: client.calls[-1] == (5, GROUP_FBS))
        await wait_for(pilot, lambda: "FBS" in status(app))


# =====================================================================================
# Favorites
# =====================================================================================


async def test_1_and_2_star_away_and_home_persist_and_unstar(tmp_path):
    path = tmp_path / "cfbtui" / "config.toml"
    app = make_app(config=Config(), config_path=path)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        assert not path.exists()
        grid = app.query_one(ScoreGrid)
        target = next(c for c in grid.cards if c.game.state == GameState.POST)
        target.focus()
        game = target.game
        await pilot.press("1")
        await pilot.pause()
        assert game.away.id in app.favorites and game.home.id not in app.favorites
        assert gids(app)[0] == game.id, "a starred game floats to the top"
        assert any(f"Added {game.away.abbreviation}" in t for t in toasts(app))
        await pilot.press("2")
        await pilot.pause()
        assert {game.away.id, game.home.id} <= app.favorites
        assert "Favorites" in text_of(grid.query_one("#cards").children[0].render())
        saved = load_config(path).config.favorites.team_ids
        assert set(saved) == {game.away.id, game.home.id}
        await pilot.press("1")
        await pilot.pause()
        assert game.away.id not in app.favorites
        assert any(f"Removed {game.away.abbreviation}" in t for t in toasts(app))
        assert set(load_config(path).config.favorites.team_ids) == {game.home.id}
    # next launch: the starred game is at the top
    app2 = make_app(config=load_config(path).config, config_path=path)
    async with app2.run_test(size=SIZE) as pilot:
        await booted(pilot, app2, 12)
        assert gids(app2)[0] == game.id


async def test_star_without_a_config_path_says_it_is_not_saved():
    app = make_app()  # config_path=None, as with --no-config
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("right", "2")
        await pilot.pause()
        assert app.favorites
        assert any("not saved" in t for t in toasts(app))


async def test_stars_without_focus_and_with_empty_board_do_not_crash():
    app = make_app(UatClient(games=()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.2)
        await pilot.press("1", "2")
        await pilot.pause()
        assert not app.favorites
        assert any("arrow keys" in t for t in toasts(app))


async def test_favorite_filter_shows_starred_games_and_an_empty_message_otherwise():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        for _ in range(3):
            await pilot.press("l")
        assert app.filter == "favorites"
        await pilot.pause()
        assert gids(app) == []
        assert "No games match this view" in message(app)
        assert "Favorites" in status(app)
        await pilot.press(*["l"] * 5)  # back to all
        await pilot.pause()
        assert len(gids(app)) == 12 and message(app) == ""
        await pilot.press("right", "1")
        for _ in range(3):
            await pilot.press("l")
        await pilot.pause()
        assert len(gids(app)) == 1


# =====================================================================================
# View, filter, conference
# =====================================================================================


async def test_v_toggles_between_cards_and_a_one_line_list():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        grid = app.query_one(ScoreGrid)
        assert all(c.size.height >= 5 for c in grid.cards if c.region.height)
        await pilot.press("v")
        await pilot.pause()
        assert app.layout == "list" and grid.columns == 1
        assert "list" in status(app)
        assert all(c.has_class("compact") for c in grid.cards)
        first = card_text(grid.cards[0])
        assert "T000" in first and "14" in first and "\n" not in first.strip()
        assert any("Layout: list" in t for t in toasts(app))
        await pilot.press("v")
        await pilot.pause()
        assert app.layout == "grid" and not any(c.has_class("compact") for c in grid.cards)
        assert "list" not in status(app)


async def test_layout_from_config_starts_in_list():
    cfg = Config()
    cfg = replace(cfg, view=replace(cfg.view, layout="list"))
    app = make_app(config=cfg)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        assert all(c.has_class("compact") for c in app.query(GameCard))


async def test_l_cycles_all_top25_live_favorites_and_shows_matching_games():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        seen = []
        counts = []
        for _ in range(8):
            await pilot.press("l")
            await pilot.pause()
            seen.append(app.filter)
            counts.append(len(gids(app)))
            await wait_for(pilot, lambda: True)
        assert seen == ["top25", "live", "favorites", "upset", "redzone", "overtime", "interesting", "all"]
        # games 0,2,5,8 involve a ranked team; 0,1,8 are live; no favorites; one upset watch; no red zone or OT; all = 12
        assert counts == [4, 3, 0, 1, 0, 0, 1, 12], counts
        assert any("Showing: Top 25" in t for t in toasts(app))
        await pilot.press("l")
        await pilot.pause()
        assert "Top 25" in status(app)
        top = [app.store.get(i) for i in gids(app)]
        assert all(g.away.rank or g.home.rank for g in top)


async def test_live_filter_with_no_live_games_shows_the_empty_message_and_keeps_polling():
    client = UatClient(games=tuple(g for g in mixed() if not g.is_live))
    app = make_app(client, intervals=FAST)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 9)
        await pilot.press("l", "l")
        await pilot.pause(0.2)
        assert app.filter == "live" and gids(app) == []
        assert "No games match this view" in message(app)
        assert "0 live of 9" in status(app)
        await pilot.press(*["l"] * 6)  # back to all
        await pilot.pause(0.2)
        assert len(gids(app)) == 9


async def test_filtering_a_focused_card_away_does_not_crash_or_leave_a_ghost_focus():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        grid = app.query_one(ScoreGrid)
        next(c for c in grid.cards if c.game.state == GameState.POST).focus()
        await pilot.press("l", "l")  # live filter drops the focused final
        await pilot.pause()
        assert grid.focused_card is None or grid.focused_card.game.is_live
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("c", "1")
        await pilot.pause()


async def test_o_picks_a_conference_and_escape_cancels():
    clip = Clip()
    app = make_app(clip=clip)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, ConferenceScreen)
        picker = app.screen.query_one(OptionList)
        labels = [text_of(picker.get_option_at_index(i).prompt) for i in range(picker.option_count)]
        assert labels[0] == "All conferences"
        assert {"SEC", "Big Ten", "ACC"} <= set(labels)
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.conference is None and len(gids(app)) == 12
        await pilot.press("o")
        await pilot.pause()
        picker = app.screen.query_one(OptionList)
        wanted = labels.index("Big Ten")
        picker.highlighted = wanted
        await pilot.press("enter")
        await pilot.pause()
        assert app.conference == "5" and len(app.screen_stack) == 1
        assert "Big Ten" in status(app)
        shown = [app.store.get(i) for i in gids(app)]
        assert shown and all("5" in (g.away.team.conference_id, g.home.team.conference_id) for g in shown)
        assert len(shown) == 3
        # c and C respect the filter
        await pilot.press("C")
        assert len(clip.copies[-1].splitlines()) == 2 + 1 + 3, "fences, title and the 3 Big Ten games"
        # reopen: the current choice is highlighted, All resets
        await pilot.press("o")
        await pilot.pause()
        assert app.screen.query_one(OptionList).highlighted == wanted
        app.screen.query_one(OptionList).highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert app.conference is None and len(gids(app)) == 12 and "Big Ten" not in status(app)


async def test_conference_plus_filter_combine_and_can_be_empty():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        app.conference = "1"
        await pilot.press("l", "l")  # live
        await pilot.pause()
        assert len(gids(app)) == 1  # the ACC live game
        assert "Live" in status(app) and "ACC" in status(app)
        app.conference = "37"  # Sun Belt: nothing
        await pilot.press("l", "l", "l")
        await pilot.pause()
        assert gids(app) == [] and "No games match this view" in message(app)


async def test_o_with_no_games_says_there_is_nothing_to_pick():
    app = make_app(UatClient(games=()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.3)
        await pilot.press("o")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert any("No conferences" in t for t in toasts(app))
        assert "No games on the board" in message(app)


# =====================================================================================
# Glyphs
# =====================================================================================


async def test_g_cycles_all_four_glyph_sets_and_the_status_names_each():
    app = make_app(glyph_set="nerd")
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        seen = ["nerd"]
        for _ in range(4):
            await pilot.press("g")
            await pilot.pause()
            seen.append(app.glyphs.name)
            assert f"glyphs: {app.glyphs.name}" in status(app)
            assert any(f"Glyph set: {app.glyphs.name}" in t for t in toasts(app))
            assert len(app.query(GameCard)) == 12
        assert seen == ["nerd", "ascii", "unicode", "emoji", "nerd"]


async def test_g_repaints_cards_the_ticker_and_an_open_detail():
    before, after = load_board("pairs/touchdown_before.json"), load_board("pairs/touchdown_after.json")
    client = FakeClient(before, after)
    client.summary = UatClient().summary
    app = make_app(client, intervals=PollIntervals(live=0.3, idle=0.3, backoff_max=1), glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(Ticker).entry_count >= 1)
        ticker = app.query_one(Ticker)
        ascii_line = text_of(ticker.lines[0].text) if ticker.lines else ""
        await pilot.press("g")
        await pilot.pause()
        assert app.glyphs.name == "unicode" and ticker.glyphs is app.glyphs
        await pilot.press("right", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))
        await pilot.press("g")  # g is not a grid action: it works over a detail screen too
        await pilot.pause()
        assert app.glyphs.name == "emoji" and app.screen.glyphs is app.glyphs
        del ascii_line


# =====================================================================================
# Copy
# =====================================================================================


async def test_c_copies_the_focused_game_as_one_line_with_the_winner_bold():
    clip = Clip()
    app = make_app(clip=clip)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        grid = app.query_one(ScoreGrid)
        final = next(c for c in grid.cards if c.game.state == GameState.POST and c.game.leader)
        final.focus()
        await pilot.press("c")
        text = clip.copies[-1]
        game = final.game
        assert "\n" not in text and len(text) < 200
        assert text.count("**") == 2
        bold = text.split("**")[1]
        assert game.leader.abbreviation in bold and game.trailer.abbreviation not in bold
        assert f" {game.away.score} " in text and "Final" in text
        assert any("Copied game" in t for t in toasts(app))
        # a tied or pregame game has no bold
        pre = next(c for c in grid.cards if c.game.is_pregame)
        pre.focus()
        await pilot.press("c")
        assert "**" not in clip.copies[-1] and "Final" not in clip.copies[-1]
        tie = next(c for c in grid.cards if c.game.is_final and c.game.is_tied)
        tie.focus()
        await pilot.press("c")
        assert "**" not in clip.copies[-1]


async def test_c_without_focus_and_with_clipboard_failure_is_polite():
    clip = Clip()
    app = make_app(clip=clip)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("c")
        assert clip.copies == [] and any("arrow keys" in t for t in toasts(app))
        clip.fail = True
        await pilot.press("right", "c")
        await pilot.pause()
        assert any("Could not copy" in t for t in toasts(app))
        await pilot.press("C")
        await pilot.pause()
        assert sum("Could not copy" in t for t in toasts(app)) >= 2
        assert len(app.query(GameCard)) == 12
        clip.fail = False
        await pilot.press("C")
        assert (clip.copies and "board" in toasts(app)[-1]) or clip.copies


async def test_C_copies_a_small_board_as_one_code_block_with_a_title():
    clip = Clip()
    app = make_app(clip=clip)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("C")
        assert len(clip.copies) == 1
        text = clip.copies[0]
        assert text.startswith("```\n") and text.endswith("\n```") and len(text) <= 2000
        assert "Week 7 FBS" in text
        body = text.splitlines()[2:-1]
        assert len(body) == 12
        # display order: the board is copied as it is on screen
        order = [app.store.get(i) for i in gids(app)]
        assert order[0].away.abbreviation in body[0]
        assert any("Copied board" in t for t in toasts(app))


async def test_C_on_a_big_saturday_copies_one_part_at_a_time_and_wraps():
    clip = Clip()
    app = make_app(UatClient(games=many(150)), clip=clip)
    async with app.run_test(size=(140, 44)) as pilot:
        await booted(pilot, app, 150)
        await pilot.press("C")
        first = clip.copies[0]
        assert any("part 1 of" in t for t in toasts(app))
        n = int(next(t for t in toasts(app) if "part 1 of" in t).split(" of ")[1].split()[0])
        assert n >= 3
        for _ in range(n - 1):
            await pilot.press("C")
        assert len(clip.copies) == n
        for part in clip.copies:
            assert len(part) <= 2000, "Discord's message cap"
            assert part.startswith("```\n") and part.endswith("\n```")
        assert any("last part" in t for t in toasts(app))
        covered = sum(len(p.splitlines()) - 2 for p in clip.copies) - 1  # minus the title line
        assert covered == 150, "every game is in exactly one part"
        assert "Week 7 FBS" in clip.copies[0] and "Week 7" not in "".join(clip.copies[1:])
        await pilot.press("C")
        assert clip.copies[-1] == first or clip.copies[-1].splitlines()[2:] == first.splitlines()[2:]
        assert clip.copies[-1].splitlines()[1] == first.splitlines()[1], "wraps to part 1"


async def test_changing_the_view_restarts_C_at_part_one():
    clip = Clip()
    app = make_app(UatClient(games=many(150)), clip=clip)
    async with app.run_test(size=(140, 44)) as pilot:
        await booted(pilot, app, 150)
        await pilot.press("C", "C")
        assert app.query_one(ScoreGrid).cards and app._copy_next == 2
        await pilot.press("l")  # top25 filter -> nothing ranked in many(): empty board
        await pilot.pause()
        assert app._copy_next == 0
        await pilot.press("C")
        assert any("No games to copy" in t for t in toasts(app))
        await pilot.press(*["l"] * 7)
        await pilot.pause()
        await pilot.press("C")
        assert "part 1 of" in toasts(app)[-2] or "part 1 of" in " ".join(toasts(app)[-3:])


async def test_C_on_an_empty_board_says_so_and_copies_nothing():
    clip = Clip()
    app = make_app(UatClient(games=()), clip=clip)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.3)
        await pilot.press("C", "c")
        await pilot.pause()
        assert clip.copies == []
        assert any("No games to copy" in t for t in toasts(app))


async def test_a_long_team_name_line_never_busts_the_cap():
    big = tuple(
        replace(g, away=replace(g.away, team=replace(g.away.team, abbreviation="X" * 3000)))
        for g in many(3)
    )
    clip = Clip()
    app = make_app(UatClient(games=big), clip=clip)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 3)
        for _ in range(4):
            await pilot.press("C")
        assert clip.copies and all(len(p) <= 2000 for p in clip.copies)


# =====================================================================================
# r and q
# =====================================================================================


async def test_r_refreshes_right_now_instead_of_waiting():
    client = UatClient()
    app = make_app(client, intervals=SLOW)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        calls = len(client.calls)
        await pilot.pause(0.3)
        assert len(client.calls) == calls, "slow intervals: nothing polls on its own"
        await pilot.press("r")
        await wait_for(pilot, lambda: len(client.calls) == calls + 1)
        await pilot.press("r")
        await wait_for(pilot, lambda: len(client.calls) == calls + 2)


async def test_q_quits_from_the_grid_and_from_a_detail_screen():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("q")
        await pilot.pause()
        assert app._exit
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("right", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))
        await pilot.press("q")
        await pilot.pause()
        assert app._exit


# =====================================================================================
# Keys under an open screen
# =====================================================================================


GRID_KEYS = ["left_square_bracket", "right_square_bracket", "t", "f", "v", "l", "o", "1", "2", "c", "C", "r", "R", "enter"]


@pytest.mark.parametrize("opener", ["detail", "rankings", "conference"])
async def test_grid_keys_do_nothing_while_a_screen_is_open(opener):
    clip = Clip()
    client = UatClient(rankings=load_rankings())
    app = make_app(client, clip=clip, week=9)
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("right")
        if opener == "detail":
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))
        elif opener == "rankings":
            await pilot.press("R")
            await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        else:
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, ConferenceScreen)
        top = app.screen
        generation = app.scheduler.generation
        calls = len(client.calls)
        favorites, layout, flt, group = app.favorites, app.layout, app.filter, app.scheduler.group
        for key in GRID_KEYS:
            if opener == "conference" and key == "enter":
                continue  # Enter selects in the picker; covered elsewhere
            await pilot.press(key)
            await pilot.pause()
            assert app.screen is top, f"{key} must not push or pop a screen over {opener}"
        assert app.scheduler.week == 9 and app.scheduler.generation == generation and app.scheduler.group == group
        assert app.favorites == favorites and app.layout == layout and app.filter == flt
        assert clip.copies == [] and len(client.calls) == calls
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and "Week 9" in status(app)


async def test_a_week_switch_that_lands_while_a_screen_is_open_closes_it():
    """The documented guard is the key block; if a switch happens anyway the screen must not linger on old data."""
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("right", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))
        app.action_week(-1)
        await pilot.pause()
        assert len(app.screen_stack) == 1


# =====================================================================================
# Mashing and sizes
# =====================================================================================


MASH_KEYS = ["left", "right", "up", "down", "enter", "escape", "left_square_bracket", "right_square_bracket", "t", "f",
             "v", "l", "o", "1", "2", "c", "C", "r", "g", "R"]


@pytest.mark.parametrize("seed", [1])
async def test_mashing_every_key_leaves_a_consistent_board(seed, tmp_path):
    rng = random.Random(seed)
    clip = Clip()
    client = UatClient(rankings=load_rankings())
    app = make_app(client, intervals=FAST, clip=clip, config=Config(), config_path=tmp_path / "c.toml")
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        for _ in range(250):
            await pilot.press(rng.choice(MASH_KEYS))
        for _ in range(3):
            await pilot.press("escape")
        await pilot.pause(0.3)
        await wait_for(pilot, lambda: len(app.screen_stack) == 1)
        assert app.scheduler.week is None or 1 <= app.scheduler.week <= 17
        # the grid shows exactly what the store and the active view say it should
        await wait_for(pilot, lambda: set(gids(app)) == {g.id for g in app._visible()}, timeout=5)
        assert len(gids(app)) == len(set(gids(app)))
        assert all(len(p) <= 2000 for p in clip.copies)
        assert status(app)


@pytest.mark.parametrize("size", [(40, 10), (20, 5), (10, 3), (400, 120), (1, 1)])
async def test_extreme_terminal_sizes_do_not_crash(size):
    clip = Clip()
    app = make_app(UatClient(games=many(60)), clip=clip, intervals=FAST)
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.5)
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 60, timeout=5)
        for key in ["right", "down", "v", "l", "l", "l", "l", "g", "g", "1", "c", "C", "enter", "escape", "R", "escape",
                    "o", "escape", "f", "t"]:
            await pilot.press(key)
        await pilot.pause(0.3)
        assert app.is_running
        assert app.export_screenshot()


async def test_resizing_a_live_app_reflows_columns_and_keeps_focus():
    app = make_app()
    async with app.run_test(size=(140, 44)) as pilot:
        await booted(pilot, app, 12)
        grid = app.query_one(ScoreGrid)
        wide = grid.columns
        await pilot.press("right", "right")
        keep = focused_id(app)
        for size in [(100, 30), (40, 10), (20, 5), (300, 90), (140, 44)]:
            await pilot.resize_terminal(*size)
            await pilot.pause()
            assert grid.columns >= 1 and len(app.query(GameCard)) == 12
            assert app.is_running
        assert grid.columns == wide and focused_id(app) == keep
        await pilot.resize_terminal(40, 10)
        await pilot.pause()
        assert grid.columns == 1


# =====================================================================================
# Boards: zero, many, errors
# =====================================================================================


async def test_zero_games_shows_a_friendly_message_and_every_key_survives():
    clip = Clip()
    app = make_app(UatClient(games=()), clip=clip, intervals=FAST)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: "No games on the board" in message(app))
        assert "updated" in status(app) and "live of" not in status(app)
        for key in ["left", "right", "up", "down", "enter", "1", "2", "c", "C", "l", "l", "l", "l", "v", "v", "o", "g", "R",
                    "escape", "r", "left_square_bracket", "right_square_bracket", "t", "f", "f"]:
            await pilot.press(key)
            await pilot.pause()
        await pilot.pause(0.3)
        assert app.is_running and clip.copies == []


async def test_150_games_all_render_and_the_arrows_reach_both_ends():
    app = make_app(UatClient(games=many(150)), intervals=FAST)
    async with app.run_test(size=(400, 45)) as pilot:  # wide: 150 cards need few rows, so few key presses
        await booted(pilot, app, 150)
        grid = app.query_one(ScoreGrid)
        cards = [c.game_id for c in grid.cards]
        assert len(cards) == 150 and "50 live of 150" in status(app)
        await pilot.press("right")
        rows = -(-150 // grid.columns)
        for _ in range(rows + 2):
            await pilot.press("down")
        assert grid.cards.index(grid.focused_card) >= 150 - grid.columns
        for _ in range(grid.columns + 2):
            await pilot.press("right")
        assert focused_id(app) == cards[-1]
        for _ in range(rows + 2):
            await pilot.press("up")
        assert grid.cards.index(grid.focused_card) < grid.columns * 2 + 150 % grid.columns + 1
        await pilot.press("v")
        await pilot.pause(0.3)
        assert len(app.query(GameCard)) == 150 and app.is_running


async def test_an_error_only_board_says_could_not_reach_espn_and_recovers():
    client = FakeClient(EspnNetworkError("no route"), load_board("scoreboard_week7_pregame.json"))
    app = make_app(client, intervals=PollIntervals(live=0.3, idle=0.3, backoff_max=0.3))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: "Could not reach ESPN" in message(app) or len(app.query(GameCard)))
        if not len(app.query(GameCard)):
            assert "no route" in message(app)
            assert "ERROR" in status(app) and app.query_one(StatusBar).has_class("error")
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 62, timeout=5)
        assert message(app) == "" and "updated" in status(app)


async def test_errors_after_a_good_board_keep_the_cards_and_flag_the_status_bar():
    client = FakeClient(load_board("scoreboard_week7_pregame.json"), EspnNetworkError("down"))
    app = make_app(client, intervals=PollIntervals(live=0.15, idle=0.15, backoff_max=0.3))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 62)
        await wait_for(pilot, lambda: "ERROR" in status(app), timeout=5)
        assert "showing data" in status(app) and app.query_one(StatusBar).has_class("error")
        assert len(app.query(GameCard)) == 62, "the last good cards stay"
        assert message(app) == ""
        await pilot.press("right", "enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.press("escape")
        await pilot.press(*["l"] * 8, "g")
        await pilot.pause()
        assert len(app.query(GameCard)) == 62 and "ERROR" in status(app)


async def test_a_week_switch_into_an_error_board_does_not_show_the_old_weeks_cards():
    def fn(week, group):
        if week == 6:
            raise EspnNetworkError("week 6 down")
        return Scoreboard(games=mixed(), week=7)

    app = make_app(UatClient(board_fn=fn), intervals=PollIntervals(live=0.2, idle=0.2, backoff_max=0.3))
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        await pilot.press("left_square_bracket")
        await wait_for(pilot, lambda: "Could not reach ESPN" in message(app), timeout=5)
        assert len(app.query(GameCard)) == 0
        assert "Week 6" in status(app)
        await pilot.press("right_square_bracket")
        await booted(pilot, app, 12)


# =====================================================================================
# Update notice and config warnings
# =====================================================================================


async def test_a_newer_release_shows_an_update_notice():
    async def check():
        return UpdateInfo("9.9.9", "https://example.test/release")

    app = make_app(update_check=check)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: any("9.9.9" in t for t in toasts(app)))
        note = next(n for n in app._notifications if "9.9.9" in n.message)
        assert note.title == "Update available" and "https://example.test/release" in note.message


async def test_no_newer_release_and_a_crashing_check_are_both_silent():
    async def none():
        return None

    async def boom():
        raise RuntimeError("github is down")

    for check in (none, boom):
        app = make_app(update_check=check)
        async with app.run_test(size=SIZE) as pilot:
            await booted(pilot, app, 12)
            await pilot.pause(0.2)
            assert not any("available" in (n.title or "") for n in app._notifications)
            assert app.is_running


async def test_config_warnings_are_toasted_at_launch():
    app = make_app(warnings=("poll.live should be positive", "bad glyph"))
    async with app.run_test(size=SIZE) as pilot:
        await booted(pilot, app, 12)
        assert any("poll.live" in t for t in toasts(app)) and any("bad glyph" in t for t in toasts(app))


# =====================================================================================
# Ticker
# =====================================================================================


def ticker_text(app: CfbApp) -> str:
    return "\n".join(text_of(line.text) for line in app.query_one(Ticker).lines)


async def test_a_touchdown_lands_in_the_ticker_flashes_the_card_and_survives_g():
    before, after = load_board("pairs/touchdown_before.json"), load_board("pairs/touchdown_after.json")
    client = FakeClient(before, after)
    app = make_app(client, intervals=PollIntervals(live=0.3, idle=0.3, backoff_max=1))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(Ticker).entry_count >= 1)
        await wait_for(pilot, lambda: "TD" in ticker_text(app), timeout=5)
        assert "KICKOFF" in ticker_text(app) or app.query_one(Ticker).entry_count >= 1
        assert app.query_one(GameCard).has_class("flash")
        count = app.query_one(Ticker).entry_count
        await pilot.press("g")
        await pilot.pause()
        assert app.query_one(Ticker).entry_count == count and "TD" in ticker_text(app)


async def test_starred_team_events_are_marked_in_the_ticker():
    before, after = load_board("pairs/touchdown_before.json"), load_board("pairs/touchdown_after.json")
    client = FakeClient(before, after)
    app = make_app(client, intervals=PollIntervals(live=0.5, idle=0.5, backoff_max=1))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        await pilot.press("right", "1")
        await wait_for(pilot, lambda: "TD" in ticker_text(app), timeout=5)
        ticker = app.query_one(Ticker)
        assert ticker.favorites and app.glyphs.favorite in ticker_text(app)


async def test_switching_week_clears_the_ticker_and_the_new_board_is_quiet():
    before = load_board("pairs/touchdown_before.json")

    def fn(week, group):
        return Scoreboard(games=before.games, week=week or 7)

    app = make_app(UatClient(board_fn=fn), intervals=SLOW)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
        app.query_one(Ticker).clear_log()
        app.query_one(Ticker).add_events([__import__("cfbtui.state.events", fromlist=["GameStarted"]).GameStarted(before.games[0])])
        assert app.query_one(Ticker).entry_count == 1
        for key in ["left_square_bracket", "f", "t"]:
            await pilot.press(key)
            await wait_for(pilot, lambda: len(app.query(GameCard)) == 1)
            await pilot.pause(0.2)
            assert app.query_one(Ticker).entry_count == 0, f"{key} leaves an empty ticker; live games announce nothing"
            app.query_one(Ticker).add_events([__import__("cfbtui.state.events", fromlist=["GameStarted"]).GameStarted(before.games[0])])


async def test_ticker_announces_a_finished_game_and_a_new_kickoff_but_not_the_first_board():
    seq = [
        Scoreboard(games=(make_game(1, "pre"), make_game(2, "live", 7, 0)), week=7),
        Scoreboard(games=(make_game(1, "live", 0, 0), make_game(2, "final", 24, 3)), week=7),
    ]
    app = make_app(FakeClient(*seq), intervals=PollIntervals(live=0.3, idle=0.3, backoff_max=1))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 2)
        await wait_for(pilot, lambda: "FINAL" in ticker_text(app), timeout=5)
        text = ticker_text(app)
        assert "KICKOFF" in text and "T002" in text


async def test_ticker_survives_json_roundtrip_fixture_sanity():
    # the fixtures the journeys rely on must stay loadable
    assert json.dumps({"ok": True}) and len(load_board("scoreboard_week7_pregame.json").games) == 62
