"""Detail and rankings screens, copy keys and the failing-game count, against a fake client."""
from __future__ import annotations

import io
import json
from dataclasses import replace

from rich.console import Console
from textual.widgets import Static

from cfbtui.app import CfbApp
from cfbtui.clipboard import ClipboardError
from cfbtui.espn.client import EspnNetworkError
from cfbtui.espn.models import GameState, Status
from cfbtui.espn.parse import parse_summary
from cfbtui.ui.glyphs import ASCII
from cfbtui.ui.screens.detail import DetailScreen, build_detail, play_line, win_bar
from cfbtui.ui.screens.rankings import RankingsScreen, pick_polls, poll_title
from cfbtui.ui.widgets.game_card import GameCard
from cfbtui.ui.widgets.status_bar import StatusBar
from tests.fakes import FIXTURES, FakeClient, load_board, load_game, load_rankings
from tests.test_app_smoke import FAST, SIZE, wait_for


def fixture_summary():
    return parse_summary(json.loads((FIXTURES / "summary_401856717.json").read_text(encoding="utf-8")))


class ScreenClient(FakeClient):
    """A FakeClient that also serves summaries and can fail them."""

    def __init__(self, *script, summaries=None, rankings=()) -> None:
        super().__init__(*script, rankings=rankings)
        self.summaries = list(summaries or [fixture_summary()])
        self.summary_calls = 0

    async def summary(self, event_id: str):
        self.summary_calls += 1
        item = self.summaries.pop(0) if len(self.summaries) > 1 else self.summaries[0]
        if isinstance(item, Exception):
            raise item
        return item


def screen_text(app) -> str:
    out = []
    for static in app.screen.query(Static):
        content = static.content
        if isinstance(content, str):
            out.append(content)
            continue
        buffer = io.StringIO()
        Console(file=buffer, width=200, color_system=None).print(content)
        out.append(buffer.getvalue())
    return "\n".join(out)


async def open_detail(pilot, app):
    await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
    await pilot.press("right")
    await pilot.press("enter")
    await wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))


def messages(app) -> list[str]:
    return [n.message for n in app._notifications]


# --- pure helpers ------------------------------------------------------------------


def test_win_bar_fills_from_the_home_side_and_vanishes_without_a_number():
    game = load_game("pairs/final_after.json")
    bar = win_bar(0.75, game, ASCII, width=20)
    assert bar.count("#") == 15 and bar.count("-") == 5
    assert "75%" in bar and "25%" in bar
    assert win_bar(None, game, ASCII) is None
    assert "100%" in win_bar(1.7, game, ASCII)


def test_play_line_carries_clock_team_text_and_running_score():
    summary = fixture_summary()
    game = load_game("pairs/final_after.json")
    line = play_line(summary.scoring_plays[0], game, ASCII)
    assert line.startswith("Q1 6:56") and "TEX" in line and "Cam Coleman" in line and "7 -" in line


def test_detail_with_no_summary_says_loading_and_with_no_plays_says_none():
    game = load_game("pairs/final_after.json")
    assert "Loading" in str(build_detail(game, None, ASCII).renderables[-1])
    empty = parse_summary({})
    assert "No scoring yet" in str(build_detail(game, empty, ASCII).renderables[-1])


def test_pick_polls_takes_ap_then_coaches_and_skips_fcs():
    polls = pick_polls(load_rankings())
    assert [p.type for p in polls] == ["ap", "usa"]
    assert "Oct 11" in poll_title(polls[0]) and "Week 7" in poll_title(polls[0])


def test_every_optional_key_removed_still_parses():
    payload = json.loads((FIXTURES / "summary_401856717.json").read_text(encoding="utf-8"))
    for key in list(payload):
        if key != "header":
            payload.pop(key)
    payload["header"] = {"id": "401856717"}
    summary = parse_summary(payload)
    assert summary.game_id == "401856717"
    assert summary.scoring_plays == () and summary.home_win_probability is None


# --- detail screen -----------------------------------------------------------------


async def test_enter_opens_detail_with_scoring_plays_and_escape_closes_it():
    client = ScreenClient(load_board("pairs/final_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await wait_for(pilot, lambda: "Scoring plays" in screen_text(app))
        text = screen_text(app)
        assert "Cam Coleman" in text and "100%" in text
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, DetailScreen))
        assert len(app.query(GameCard)) == 1


async def test_enter_with_nothing_focused_only_says_so():
    client = ScreenClient(load_board("pairs/final_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, DetailScreen)
        assert any("Focus a card" in m for m in messages(app))


async def test_a_live_game_refreshes_until_the_screen_closes_and_then_stops():
    live = replace(fixture_summary(), status=Status(state=GameState.IN, name="STATUS_IN_PROGRESS"))
    client = ScreenClient(load_board("pairs/touchdown_before.json"), summaries=[live])
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", detail_refresh=0.05)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await wait_for(pilot, lambda: client.summary_calls >= 3)
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, DetailScreen))
        await pilot.pause(0.1)
        settled = client.summary_calls
        await pilot.pause(0.3)
        assert client.summary_calls == settled, "the fetch loop is gone with the screen"
        assert not [w for w in app.workers if w.name == "detail" and not w.is_finished]


async def test_a_fetch_that_lands_after_escape_paints_nothing_and_does_not_raise():
    """Escape removes the widgets before the worker is cancelled; a fetch already in flight must not crash the app."""
    client = ScreenClient(load_board("pairs/touchdown_before.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", detail_refresh=0.05)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        screen = app.screen
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, DetailScreen))
        await pilot.pause(0.1)
        screen._paint()  # what the worker does when its fetch returns
        assert not screen.is_attached


async def test_a_final_game_is_fetched_once():
    client = ScreenClient(load_board("pairs/final_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", detail_refresh=0.05)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await wait_for(pilot, lambda: "Scoring plays" in screen_text(app))
        await pilot.pause(0.3)
        assert client.summary_calls == 1


async def test_a_failed_fetch_says_so_and_recovers():
    client = ScreenClient(
        load_board("pairs/touchdown_before.json"),
        summaries=[EspnNetworkError("cable pulled"), fixture_summary()],
    )
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", detail_refresh=0.05)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await wait_for(pilot, lambda: "Scoring plays" in screen_text(app))
        assert "Could not refresh" not in screen_text(app), "a good fetch clears the warning"
    failing = ScreenClient(load_board("pairs/final_after.json"), summaries=[EspnNetworkError("cable pulled")])
    app = CfbApp(client=failing, intervals=FAST, glyph_set="ascii", detail_refresh=0.05)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await wait_for(pilot, lambda: "Could not refresh" in screen_text(app))


async def test_a_week_switch_from_code_closes_the_open_detail():
    client = ScreenClient(load_board("pairs/touchdown_before.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", week=7)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        before = app.week
        await pilot.press("right_square_bracket")
        await pilot.press("f")
        await pilot.pause(0.1)
        assert app.week == before, "grid keys are off while a screen is open"
        app.action_week(1)  # a switch from code closes the screen showing the old week
        await wait_for(pilot, lambda: not isinstance(app.screen, DetailScreen))
        assert len(app.screen_stack) == 1


async def test_poll_updates_reach_the_open_detail_header():
    client = ScreenClient(load_board("pairs/touchdown_before.json"), load_board("pairs/touchdown_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", detail_refresh=10)
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await wait_for(pilot, lambda: app.screen.game.away.score == 14)


# --- rankings screen ---------------------------------------------------------------


async def test_r_shows_both_polls_and_escape_returns():
    client = ScreenClient(load_board("pairs/final_after.json"), rankings=load_rankings())
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        titles = [w.border_title for w in app.screen.query(".poll")]
        assert len(titles) == 2 and "AP Top 25" in titles[0] and "Oct 11" in titles[0]
        assert "Coaches" in titles[1]
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, RankingsScreen))


async def test_c_on_rankings_copies_one_poll_per_press_for_discord():
    client = ScreenClient(load_board("pairs/final_after.json"), rankings=load_rankings())
    app = CfbApp(client=client, intervals=FAST, glyph_set="nerd")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        copied: list[str] = []
        app.screen.copier = copied.append
        await pilot.press("c")
        assert len(copied) == 1 and "AP Top 25" in copied[0] and copied[0].startswith("```")
        assert any("Copied AP Top 25, part 1 of 2" in m for m in messages(app))
        await pilot.press("c")
        assert len(copied) == 2 and "Coaches" in copied[1] and len(copied[1]) <= 2000
        assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in "".join(copied)), "no Nerd Font glyphs reach Discord"
        await pilot.press("c")
        assert copied[2] == copied[0], "after the last part it starts over"


async def test_c_on_rankings_with_no_polls_says_so():
    app = CfbApp(client=ScreenClient(load_board("pairs/final_after.json"), rankings=()), intervals=FAST)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        copied: list[str] = []
        app.screen.copier = copied.append
        await pilot.press("c")
        assert copied == [] and any("No rankings" in m for m in messages(app))


async def test_rankings_failure_says_so():
    class Broken(ScreenClient):
        async def rankings(self):
            raise EspnNetworkError("no route")

    app = CfbApp(client=Broken(load_board("pairs/final_after.json")), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        assert "Could not load the polls" in screen_text(app)
        assert app.screen.polls == []


async def test_rankings_with_no_polls_yet():
    app = CfbApp(client=ScreenClient(load_board("pairs/final_after.json"), rankings=()), intervals=FAST)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("R")
        await wait_for(pilot, lambda: isinstance(app.screen, RankingsScreen) and app.screen.loaded)
        assert "No polls" in screen_text(app)


# --- copy --------------------------------------------------------------------------


async def test_c_copies_the_focused_game_as_markdown_in_unicode():
    client = ScreenClient(load_board("pairs/final_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="nerd")
    copied: list[str] = []
    app.copier = copied.append
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("c")
        assert copied == [] and any("Focus a card" in m for m in messages(app))
        await pilot.press("right")
        await pilot.press("c")
        assert len(copied) == 1 and "**" in copied[0] and "Final" in copied[0]
        assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in copied[0]), "no Nerd Font glyphs reach Discord"


async def test_shift_c_copies_the_whole_board_and_needs_no_focus():
    client = ScreenClient(load_board("scoreboard_week7_pregame.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    copied: list[str] = []
    app.copier = copied.append
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("C")
        assert len(copied) == 1 and copied[0].startswith("```\nWeek 7 FBS")
        assert copied[0].endswith("```") and len(copied[0]) <= 2000


async def test_a_missing_clipboard_is_a_message_not_a_crash():
    client = ScreenClient(load_board("pairs/final_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")

    def broken(text: str) -> None:
        raise ClipboardError("no copy mechanism")

    app.copier = broken
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("C")
        assert any("Could not copy" in m for m in messages(app))


async def test_a_long_board_is_copied_a_part_at_a_time():
    base = load_board("scoreboard_week7_pregame.json")

    games = tuple(replace(base.games[i % len(base.games)], id=f"g{i}") for i in range(60))
    client = ScreenClient(replace(base, games=games))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    copied: list[str] = []
    app.copier = copied.append
    async with app.run_test(size=(140, 200)) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) == 60)
        await pilot.press("C")
        await pilot.press("C")
        assert len(copied) == 2 and copied[0] != copied[1]
        assert all(len(c) <= 2000 for c in copied)


# --- failing games -----------------------------------------------------------------


async def test_the_status_bar_counts_games_that_fail_to_diff():
    client = ScreenClient(load_board("pairs/final_after.json"))
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        assert "failing" not in app.query_one(StatusBar).text
        app.store.last_errors = [("1", ValueError("boom"))]
        app._tick()
        assert "1 game failing to diff" in app.query_one(StatusBar).text


def test_pick_polls_for_the_fcs_board_is_the_fcs_coaches_poll():
    from cfbtui.espn.client import GROUP_FCS

    polls = pick_polls(load_rankings(), GROUP_FCS)
    assert [p.type for p in polls] == ["fcs"]


async def test_q_on_a_screen_still_quits():
    app = CfbApp(client=ScreenClient(load_board("pairs/final_after.json")), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await open_detail(pilot, app)
        await pilot.press("q")
        await pilot.pause(0.2)
    assert not app.is_running
