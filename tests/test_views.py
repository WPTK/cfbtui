"""Postseason weeks, the CFP-only rankings rule, filters, the list layout, favorites heading and the conference picker."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from cfbtui.__main__ import _week, build_parser
from cfbtui.app import CfbApp
from cfbtui.config import Config, FavoritesConfig, ViewConfig, parse_config
from cfbtui.espn.client import GROUP_FCS, EspnClient
from cfbtui.espn.models import Competitor, Game, GameState, RankEntry, Ranking, Situation, Status, Team
from cfbtui.espn.parse import parse_scoreboard
from cfbtui.espn.periods import WEEK_BOWLS, WEEK_PLAYOFF, espn_request, from_espn, week_label
from cfbtui.state.upset import UpsetRule
from cfbtui.ui.filters import (
    CONFERENCES,
    conference_name,
    conferences_on,
    describe,
    is_interesting,
    is_overtime,
    is_upset_watch,
    keep,
    next_filter,
)
from cfbtui.ui.glyphs import ASCII, UNICODE
from cfbtui.ui.screens.conferences import ConferenceScreen
from cfbtui.ui.screens.rankings import is_cfp, pick_polls
from cfbtui.ui.widgets.game_card import GameCard, compact_line
from cfbtui.ui.widgets.score_grid import ScoreGrid
from cfbtui.ui.widgets.status_bar import StatusBar
from tests.fakes import FIXTURES, FakeClient, load_board
from tests.test_app_smoke import FAST, SIZE, wait_for

RULE = UpsetRule()


def poll(kind: str, name: str, ranks: int = 3) -> Ranking:
    entries = tuple(
        RankEntry(team_id=str(i), abbreviation=f"T{i}", name=f"Team {i}", color="000000", rank=i + 1) for i in range(ranks)
    )
    return Ranking(id=kind, name=name, short_name=name, type=kind, ranks=entries)


# --- weeks outside the regular season ---------------------------------------


def test_week_labels():
    assert week_label(7) == "Week 7"
    assert week_label(WEEK_BOWLS) == "Bowls"
    assert week_label(WEEK_PLAYOFF) == "Playoff"


def test_espn_request_and_back():
    assert espn_request(7) == (7, 2)
    assert espn_request(None) == (None, None)
    assert espn_request(WEEK_BOWLS) == (1, 3)
    assert espn_request(WEEK_PLAYOFF) == (999, 3)
    assert from_espn(7, 2) == 7
    assert from_espn(1, 3) == WEEK_BOWLS
    assert from_espn(999, 3) == WEEK_PLAYOFF
    assert from_espn(None, 3) is None


def test_a_postseason_payload_becomes_the_bowls_or_playoff_week():
    raw = json.loads((FIXTURES / "scoreboard_week7_pregame.json").read_text(encoding="utf-8"))
    raw["season"] = {"type": 3, "year": 2026}
    raw["week"] = {"number": 1}
    assert parse_scoreboard(raw).week == WEEK_BOWLS
    raw["week"] = {"number": 999}
    assert parse_scoreboard(raw).week == WEEK_PLAYOFF


@respx.mock
async def test_the_client_asks_espn_for_postseason_slots():
    route = respx.get(url__regex=r".*/scoreboard").mock(return_value=httpx.Response(200, json={"events": []}))
    async with EspnClient() as client:
        await client.scoreboard(week=WEEK_PLAYOFF)
        await client.scoreboard(week=WEEK_BOWLS)
        await client.scoreboard(week=7)
    queries = [dict(call.request.url.params) for call in route.calls]
    assert queries[0]["week"] == "999" and queries[0]["seasontype"] == "3"
    assert queries[1]["week"] == "1" and queries[1]["seasontype"] == "3"
    assert queries[2]["week"] == "7" and queries[2]["seasontype"] == "2"


def test_the_command_line_and_config_accept_bowls_and_playoff():
    assert _week("bowls") == WEEK_BOWLS
    assert _week("Playoff") == WEEK_PLAYOFF
    assert _week("17") == 17
    with pytest.raises(argparse.ArgumentTypeError):
        _week("18")
    assert build_parser().parse_args(["--week", "playoff"]).week == WEEK_PLAYOFF
    config, warnings = parse_config({"view": {"week": 16}})
    assert config.view.week == WEEK_BOWLS and not warnings
    _, warnings = parse_config({"view": {"week": 18}})
    assert warnings


# --- rankings: CFP replaces AP and Coaches ----------------------------------


def test_without_a_cfp_ranking_the_fbs_board_shows_ap_and_coaches():
    polls = (poll("ap", "AP Top 25"), poll("usa", "AFCA Coaches Poll"), poll("fcs", "FCS Coaches Poll"))
    assert [p.type for p in pick_polls(polls)] == ["ap", "usa"]


def test_the_first_cfp_ranking_is_the_only_ranking_from_then_on():
    cfp = poll("cfp", "Playoff Committee Rankings")
    polls = (poll("ap", "AP Top 25"), poll("usa", "AFCA Coaches Poll"), cfp)
    assert pick_polls(polls) == [cfp]
    assert is_cfp(cfp) and not is_cfp(polls[0])


def test_a_remembered_cfp_ranking_survives_a_payload_that_stops_listing_it():
    cfp = poll("cfp", "Playoff Committee Rankings")
    later = (poll("ap", "AP Top 25"), poll("usa", "AFCA Coaches Poll"))
    assert pick_polls(later, remembered_cfp=cfp) == [cfp]


def test_an_empty_cfp_poll_does_not_replace_the_others():
    polls = (poll("ap", "AP Top 25"), poll("cfp", "Playoff Committee Rankings", ranks=0))
    assert [p.type for p in pick_polls(polls)] == ["ap"]


def test_the_fcs_board_never_shows_the_cfp():
    polls = (poll("cfp", "Playoff Committee Rankings"), poll("fcs", "FCS Coaches Poll"))
    assert [p.type for p in pick_polls(polls, GROUP_FCS)] == ["fcs"]


# --- filters ----------------------------------------------------------------


def board():
    return load_board("scoreboard_week7_pregame.json")


def test_filters_cycle_and_describe():
    seen, mode = [], "all"
    for _ in range(8):
        mode = next_filter(mode)
        seen.append(mode)
    assert seen == ["top25", "live", "favorites", "upset", "redzone", "overtime", "interesting", "all"]
    assert describe("all", None, "grid") == ""
    assert describe("top25", "8", "list") == "Top 25 SEC list"


def test_keep_top25_favorites_and_conference():
    games = board().games
    ranked = [g for g in games if g.away.rank is not None or g.home.rank is not None]
    assert ranked and len(ranked) < len(games)
    assert [g for g in games if keep(g, "top25", frozenset(), None, RULE)] == ranked
    assert not [g for g in games if keep(g, "live", frozenset(), None, RULE)]
    star = ranked[0].home.id
    assert [g for g in games if keep(g, "favorites", frozenset({star}), None, RULE)]
    assert all(g.home.id == star or g.away.id == star for g in games if keep(g, "favorites", frozenset({star}), None, RULE))
    sec = [g for g in games if keep(g, "all", frozenset(), "8", RULE)]
    assert sec and all("8" in (g.away.team.conference_id, g.home.team.conference_id) for g in sec)


def test_conferences_on_the_board_are_named_and_sorted():
    options = conferences_on(board().games)
    names = [name for _, name in options]
    assert ("8", "SEC") in options and ("1", "ACC") in options
    named = [n for i, n in options if i in CONFERENCES]
    assert named == sorted(named)
    assert names[: len(named)] == named  # unnamed ones sort last
    assert conference_name("99999") == "Conference 99999"


def mk(
    *,
    state: GameState = GameState.IN,
    period: int = 2,
    home: int = 0,
    away: int = 0,
    away_rank: int | None = None,
    red_zone: bool = False,
    conf: str = "8",
    completed: bool = False,
) -> Game:
    def t(abbr: str, i: str) -> Team:
        return Team(id=i, abbreviation=abbr, display_name=abbr, short_name=abbr, color="#000000",
                    alt_color="#ffffff", conference_id=conf)

    return Game(
        id="1",
        date=datetime(2026, 10, 10, tzinfo=UTC),
        name="Away at Home",
        short_name="AWY @ HOM",
        home=Competitor(team=t("HOM", "201"), home_away="home", score=home),
        away=Competitor(team=t("AWY", "251"), home_away="away", score=away, rank=away_rank),
        status=Status(state=state, completed=completed, period=period),
        situation=Situation(is_red_zone=red_zone) if state == GameState.IN else None,
    )


def test_upset_watch_is_a_live_underdog_lead_only():
    watch = mk(away_rank=3, home=17, away=10)
    assert is_upset_watch(watch, RULE)
    assert not is_upset_watch(mk(away_rank=3, home=10, away=17), RULE)
    assert not is_upset_watch(mk(away_rank=3, home=17, away=10, state=GameState.POST, completed=True), RULE)
    assert not is_upset_watch(mk(state=GameState.PRE, away_rank=3), RULE)


def test_red_zone_filter_matches_the_card_definition():
    hot = mk(red_zone=True)
    assert hot.in_red_zone and keep(hot, "redzone", frozenset(), None, RULE)
    assert not keep(mk(), "redzone", frozenset(), None, RULE)
    assert not keep(mk(state=GameState.POST, completed=True), "redzone", frozenset(), None, RULE)


def test_overtime_includes_live_and_finished_but_not_regulation():
    assert is_overtime(mk(period=5))
    assert is_overtime(mk(period=6, state=GameState.POST, completed=True))
    assert not is_overtime(mk(period=4))
    assert not is_overtime(mk(period=5, state=GameState.PRE))


def test_interesting_is_the_union_of_the_three():
    cases = [
        mk(away_rank=3, home=17, away=10),
        mk(red_zone=True),
        mk(period=5),
        mk(),
        mk(state=GameState.PRE),
    ]
    for g in cases:
        expected = is_upset_watch(g, RULE) or g.in_red_zone or is_overtime(g)
        assert is_interesting(g, RULE) is expected
        assert keep(g, "interesting", frozenset(), None, RULE) is expected
    assert [is_interesting(g, RULE) for g in cases] == [True, True, True, False, False]


def test_new_filters_compose_with_the_conference_filter():
    sec, acc = mk(period=5, conf="8"), mk(period=5, conf="1")
    for mode in ("overtime", "interesting"):
        assert keep(sec, mode, frozenset(), "8", RULE)
        assert not keep(acc, mode, frozenset(), "8", RULE)
    assert describe("redzone", "8", "grid") == "Red Zone SEC"


# --- the list layout --------------------------------------------------------


def test_compact_line_is_one_line_with_both_teams_and_the_status():
    game = board().games[0]
    now = datetime(2026, 10, 12, tzinfo=UTC)
    text = compact_line(game, UNICODE, now=now)
    assert "\n" not in text.plain
    assert game.away.abbreviation in text.plain and game.home.abbreviation in text.plain
    assert UNICODE.at in text.plain


def test_compact_line_shows_scores_for_a_game_in_progress():
    game = load_board("pairs/touchdown_before.json").games[0]
    plain = compact_line(game, ASCII).plain
    assert str(game.away.score) in plain and str(game.home.score) in plain


# --- in the app ---------------------------------------------------------------


def client() -> FakeClient:
    return FakeClient(board())


async def cards_shown(pilot, app, count: int) -> None:
    await wait_for(pilot, lambda: len(app.query(GameCard)) == count)


async def test_v_switches_to_the_one_line_layout_and_back():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(board().games))
        assert not any(c.compact for c in app.query(GameCard))
        await pilot.press("v")
        await pilot.pause()
        assert all(c.compact for c in app.query(GameCard))
        assert all(c.size.height == 1 for c in app.query(GameCard) if c.region.height)
        assert "list" in app.query_one(StatusBar).text
        await pilot.press("v")
        await pilot.pause()
        assert not any(c.compact for c in app.query(GameCard))


async def test_the_layout_can_start_from_config():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii", config=Config(view=ViewConfig(layout="list")))
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(board().games))
        assert all(c.compact for c in app.query(GameCard))


async def test_l_cycles_the_filter_and_the_grid_follows():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        total = len(board().games)
        await cards_shown(pilot, app, total)
        await pilot.press("l")  # Top 25
        await pilot.pause()
        ranked = {g.id for g in board().games if g.away.rank is not None or g.home.rank is not None}
        assert {c.game_id for c in app.query(GameCard)} == ranked
        assert "Top 25" in app.query_one(StatusBar).text
        await pilot.press("l")  # Live: none on a pregame board
        await pilot.pause()
        assert len(app.query(GameCard)) == 0
        assert "No games match" in str(app.query_one("#message").render())
        await pilot.press(*["l"] * 6)  # Favorites, the four game-day filters, then back to all
        await pilot.pause()
        assert len(app.query(GameCard)) == total


async def test_favorites_get_a_heading_and_the_rest_another():
    games = board().games
    star = games[0].home
    config = Config(favorites=FavoritesConfig(team_ids=(star.id,)))
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii", config=config)
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(games))
        await pilot.pause(0.3)
        grid = app.query_one(ScoreGrid)
        headings = [str(h.render()) for h in grid.query(".section")]
        assert any("Favorites" in h for h in headings)
        assert any("Other games" in h for h in headings)
        order = list(grid.query_one("#cards").children)
        first_card = next(i for i, w in enumerate(order) if isinstance(w, GameCard))
        assert first_card == 1, "the Favorites heading comes first"
        assert grid.cards[0].game.home.id == star.id or grid.cards[0].game.away.id == star.id


async def test_no_headings_without_favorites():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(board().games))
        assert not list(app.query(".section"))


async def test_o_opens_the_conference_picker_and_filters():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        total = len(board().games)
        await cards_shown(pilot, app, total)
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, ConferenceScreen)
        options = [o.prompt for o in app.screen.query_one("OptionList").options]
        assert options[0] == "All conferences" and "SEC" in options
        app.screen.query_one("OptionList").highlighted = options.index("SEC")
        await pilot.press("enter")
        await pilot.pause()
        assert app.conference == "8"
        shown = list(app.query(GameCard))
        assert shown and len(shown) < total
        assert "SEC" in app.query_one(StatusBar).text
        await pilot.press("o")
        await pilot.pause()
        app.screen.query_one("OptionList").highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert app.conference is None
        await cards_shown(pilot, app, total)


async def test_escape_leaves_the_conference_filter_alone():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(board().games))
        await pilot.press("o", "escape")
        await pilot.pause()
        assert app.conference is None and not isinstance(app.screen, ConferenceScreen)


async def test_the_grid_keys_sleep_while_the_picker_is_open():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(board().games))
        await pilot.press("o")
        await pilot.pause()
        await pilot.press("v", "l")
        await pilot.pause()
        assert app.layout == "grid" and app.filter == "all"


async def test_the_week_label_reads_bowls_in_the_status_bar():
    raw = json.loads((FIXTURES / "scoreboard_week7_pregame.json").read_text(encoding="utf-8"))
    raw["season"] = {"type": 3, "year": 2026}
    raw["week"] = {"number": 1}
    postseason = parse_scoreboard(raw)
    app = CfbApp(client=FakeClient(postseason), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(postseason.games))
        assert "Bowls" in app.query_one(StatusBar).text


async def test_an_update_notice_appears_when_a_newer_release_exists():
    from cfbtui.update import UpdateInfo

    async def check():
        return UpdateInfo("9.0.0", "https://example.test/releases/latest")

    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii", update_check=check)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: any("9.0.0" in n.message for n in app._notifications))


async def test_no_update_check_means_no_network_call_and_no_notice():
    app = CfbApp(client=client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await cards_shown(pilot, app, len(board().games))
        assert not any("available" in n.message for n in app._notifications)
