"""LIVE smoke test against real ESPN. Skipped unless CFBTUI_LIVE=1.

    CFBTUI_LIVE=1 python -m pytest tests/uat/test_uat_live.py -q
"""
from __future__ import annotations

import asyncio
import os

import pytest

from cfbtui.app import CfbApp
from cfbtui.espn.client import GROUP_FBS, GROUP_FCS, EspnClient, EspnError
from cfbtui.espn.models import GameState, Scoreboard
from cfbtui.poll import PollIntervals
from cfbtui.ui.widgets.game_card import GameCard

pytestmark = pytest.mark.skipif(os.environ.get("CFBTUI_LIVE") != "1", reason="set CFBTUI_LIVE=1 to hit real ESPN")

GROUPS = [pytest.param(GROUP_FBS, id="FBS"), pytest.param(GROUP_FCS, id="FCS")]
WEEKS = [pytest.param(None, id="current"), pytest.param(1, id="week1"), pytest.param(7, id="week7")]


@pytest.fixture
async def client():
    c = EspnClient()
    try:
        yield c
    finally:
        await c.aclose()


def check_board(board: Scoreboard, *, require_games: bool) -> None:
    assert isinstance(board, Scoreboard)
    if require_games:
        assert board.games, "expected games on this board"
    ids = [g.id for g in board.games]
    assert len(ids) == len(set(ids)), "duplicate game ids"
    for g in board.games:
        where = f"game {g.id} {g.name!r}"
        assert g.id, where
        for side in (g.home, g.away):
            assert side.team.id, where
            assert side.team.display_name.strip(), f"{where}: empty team name"
            assert side.team.abbreviation.strip(), f"{where}: empty abbreviation"
            assert isinstance(side.score, int) and not isinstance(side.score, bool), where
            assert side.score >= 0, where
            assert side.rank is None or 1 <= side.rank <= 25, f"{where}: rank {side.rank}"
        assert g.home.team.id != g.away.team.id, where
        assert isinstance(g.state, GameState), where
        assert g.status.name.startswith("STATUS_"), f"{where}: odd status name {g.status.name!r}"
        assert g.date.tzinfo is not None, where
        if g.is_pregame:
            assert g.home.score == 0 and g.away.score == 0, f"{where}: pregame with a score"
        if g.is_final:
            assert g.status.completed


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("week", WEEKS)
async def test_scoreboard_parses_every_game(client, group, week):
    try:
        board = await client.scoreboard(week=week, group=group)
    except EspnError as exc:  # flaky network is not a product bug
        pytest.skip(f"ESPN unreachable: {exc}")
    # FBS always has games in weeks 1 and 7; FCS week 1 too. The current week (mid October) has games on both.
    check_board(board, require_games=True)


async def test_week1_fbs_is_all_final(client):
    board = await client.scoreboard(week=1, group=GROUP_FBS)
    unfinished = [g.name for g in board.games if not g.is_final and g.status.name != "STATUS_POSTPONED"
                  and g.status.name != "STATUS_CANCELED"]
    assert not unfinished, unfinished
    assert board.week == 1


async def test_current_week_is_plausible_for_mid_october(client):
    board = await client.scoreboard(week=None, group=GROUP_FBS)
    assert board.week is not None and 5 <= board.week <= 9, board.week
    assert board.season_year == 2026


async def test_rankings_parse(client):
    rankings = await client.rankings()
    assert rankings, "no polls returned"
    names = {r.short_name for r in rankings}
    assert any("AP" in n for n in names), names
    for poll in rankings:
        assert poll.name.strip()
        for entry in poll.ranks:
            assert entry.team_id and entry.name.strip() and entry.abbreviation.strip()
            assert entry.rank is not None
    ap = next(r for r in rankings if "AP" in r.short_name)
    assert len(ap.ranks) == 25
    assert [e.rank for e in ap.ranks] == sorted(e.rank for e in ap.ranks)


async def test_summary_for_a_finished_game(client):
    board = await client.scoreboard(week=1, group=GROUP_FBS)
    finals = [g for g in board.games if g.is_final]
    assert finals
    checked = 0
    for game in finals[:3]:
        summary = await client.summary(game.id)
        assert summary.game_id == game.id
        assert summary.status.state is GameState.POST
        for play in summary.scoring_plays:
            assert isinstance(play.away_score, int) and isinstance(play.home_score, int)
            assert play.team_abbreviation
        if summary.scoring_plays:
            last = summary.scoring_plays[-1]
            assert (last.away_score, last.home_score) == (game.away.score, game.home.score), game.name
            checked += 1
    assert checked, "none of the finished games had scoring plays"


async def test_summary_for_a_current_week_game(client):
    board = await client.scoreboard(week=None, group=GROUP_FBS)
    game = next(iter(board.games))
    summary = await client.summary(game.id)
    assert summary.game_id == game.id


async def test_app_renders_live_cards():
    app = CfbApp(intervals=PollIntervals(live=30, idle=30), glyph_set="ascii", week=7)
    async with app.run_test(size=(160, 50)) as pilot:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 25
        while not len(app.query(GameCard)) and loop.time() < deadline:
            await pilot.pause(0.1)
        cards = list(app.query(GameCard))
        assert cards, "no cards rendered"
        shown = {c.game.id for c in cards}
        assert shown == {g.id for g in app.store.games}
        for card in cards:
            assert card.model is not None
            assert card.game.home.team.display_name.strip()
        # switching to FCS and to the current week works against the real feed too
        await pilot.press("f")
        deadline = loop.time() + 25
        while loop.time() < deadline and not (app.scheduler.group == GROUP_FCS and len(app.query(GameCard))):
            await pilot.pause(0.1)
        assert app.scheduler.group == GROUP_FCS and len(app.query(GameCard)) > 0
        await pilot.press("t")
        deadline = loop.time() + 25
        while loop.time() < deadline and not (app.scheduler.week is None and len(app.query(GameCard))):
            await pilot.pause(0.1)
        assert app.scheduler.week is None and len(app.query(GameCard)) > 0
