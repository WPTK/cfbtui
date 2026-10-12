"""Week and group switching, favorites, focus, and config wiring, against a fake client."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from cfbtui.app import CfbApp
from cfbtui.config import Config, FavoritesConfig, ViewConfig, load_config, save_config
from cfbtui.espn.client import GROUP_FBS, GROUP_FCS
from cfbtui.espn.models import Ranking, Scoreboard
from cfbtui.poll import PollIntervals
from cfbtui.ui.widgets.game_card import GameCard, kickoff_text
from cfbtui.ui.widgets.score_grid import ScoreGrid, next_index, sort_key
from cfbtui.ui.widgets.status_bar import StatusBar
from cfbtui.ui.widgets.ticker import Ticker, format_event
from tests.fakes import load_board, load_game
from tests.test_app_smoke import FAST, SIZE, wait_for

import pytest


class WeekClient:
    """Serves a board per (week, group); a week listed in ``gates`` blocks until its gate opens."""

    def __init__(self, boards: dict[tuple[int | None, int], Scoreboard]) -> None:
        self.boards = boards
        self.gates: dict[tuple[int | None, int], asyncio.Event] = {}
        self.calls: list[tuple[int | None, int]] = []

    async def scoreboard(self, *, week: int | None = None, group: int = GROUP_FBS) -> Scoreboard:
        key = (week, group)
        self.calls.append(key)
        gate = self.gates.get(key)
        if gate is not None:
            await gate.wait()
        return self.boards[key]

    async def rankings(self) -> tuple[Ranking, ...]:
        return ()


def tex_oklahoma() -> Scoreboard:
    return load_board("pairs/touchdown_before.json")


def pregame() -> Scoreboard:
    return load_board("scoreboard_week7_pregame.json")


def final_game() -> Scoreboard:
    return load_board("pairs/final_after.json")


def ids(app: CfbApp) -> list[str]:
    return [c.game_id for c in app.query(GameCard)]


async def settle(pilot, app: CfbApp, expected: int) -> None:
    await wait_for(pilot, lambda: len(app.query(GameCard)) == expected)


def two_boards():
    live, week7 = tex_oklahoma(), pregame()
    return {(None, GROUP_FBS): week7, (6, GROUP_FBS): live, (8, GROUP_FBS): live, (7, GROUP_FBS): week7}, live, week7


# --- switching --------------------------------------------------------------------


async def test_brackets_move_the_week_and_t_returns_to_the_current_week():
    boards, live, week7 = two_boards()
    client = WeekClient(boards)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(week7.games))
        status = app.query_one(StatusBar)
        assert "Week 7 FBS" in status.text
        await pilot.press("left_square_bracket")
        await settle(pilot, app, len(live.games))
        assert ids(app) == [g.id for g in live.games], "only the week 6 board is on screen"
        assert client.calls[-1][0] == 6 or (6, GROUP_FBS) in client.calls
        await wait_for(pilot, lambda: "Week 6" in status.text)
        await pilot.press("t")
        await settle(pilot, app, len(week7.games))
        assert app.scheduler.week is None
        await wait_for(pilot, lambda: "Week 7" in status.text)


async def test_a_switch_clears_the_ticker_and_the_first_board_is_quiet():
    boards, live, _ = two_boards()
    client = WeekClient(boards)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        ticker = app.query_one(Ticker)
        ticker.add_events([_started(live)])
        assert ticker.entry_count == 1
        await wait_for(pilot, lambda: len(app.query(GameCard)) > 0)
        await pilot.press("left_square_bracket")
        await settle(pilot, app, len(live.games))
        await pilot.pause(0.2)
        assert ticker.entry_count == 0, "cleared by the switch, and the new live game announced nothing"


def _started(board: Scoreboard):
    from cfbtui.state.events import GameStarted

    return GameStarted(board.games[0])


async def test_a_week_switch_while_a_poll_is_in_flight_drops_the_old_board():
    boards, live, week7 = two_boards()
    client = WeekClient(boards)
    gate = client.gates[(None, GROUP_FBS)] = asyncio.Event()
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", week=None)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: client.calls == [(None, GROUP_FBS)])
        assert app.scheduler.polling
        app.scheduler.switch(week=6)  # what a key press does, while the week 7 fetch hangs
        app.query_one(ScoreGrid).clear()
        gate.set()  # the old fetch now completes with week 7's board
        await settle(pilot, app, len(live.games))
        await pilot.pause(0.2)
        assert ids(app) == [g.id for g in live.games], "the week 7 board never reached the grid"
        assert all(g.id in {x.id for x in live.games} for g in app.store.games)


async def test_a_result_queued_for_the_old_week_is_ignored():
    boards, live, week7 = two_boards()
    app = CfbApp(client=WeekClient(boards), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(week7.games))
        stale = app.last_result
        await pilot.press("left_square_bracket")
        await settle(pilot, app, len(live.games))
        from cfbtui.app import PollUpdated

        app.post_message(PollUpdated(stale))  # generation is older than the scheduler's
        await pilot.pause(0.1)
        assert ids(app) == [g.id for g in live.games]


async def test_week_edges_clamp_with_a_toast_and_no_switch():
    boards = {(1, GROUP_FBS): pregame(), (15, GROUP_FBS): pregame()}
    client = WeekClient(boards)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", week=1)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(client.calls) >= 1)
        generation = app.scheduler.generation
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.scheduler.generation == generation and app.scheduler.week == 1
        assert any("first week" in n.message for n in app._notifications)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", week=15)
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(client.calls) >= 2)
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.scheduler.week == 15
        assert any("last week" in n.message for n in app._notifications)


async def test_t_on_the_current_week_does_not_switch():
    boards, _, week7 = two_boards()
    app = CfbApp(client=WeekClient(boards), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(week7.games))
        generation = app.scheduler.generation
        await pilot.press("t")
        await pilot.pause()
        assert app.scheduler.generation == generation


async def test_f_toggles_the_group_and_keeps_the_week():
    live, week7 = tex_oklahoma(), pregame()
    boards = {(None, GROUP_FBS): week7, (None, GROUP_FCS): live, (6, GROUP_FBS): week7, (6, GROUP_FCS): live}
    client = WeekClient(boards)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii", week=6)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(week7.games))
        await pilot.press("f")
        await settle(pilot, app, len(live.games))
        assert client.calls[-1] == (6, GROUP_FCS)
        assert "FCS" in app.query_one(StatusBar).text
        await pilot.press("f")
        await settle(pilot, app, len(week7.games))
        assert client.calls[-1] == (6, GROUP_FBS)


# --- config wiring ----------------------------------------------------------------


async def test_config_sets_intervals_glyphs_week_and_group():
    config = Config(
        poll=PollIntervals(live=7, idle=77, backoff_max=9),
        view=ViewConfig(glyph_set="unicode", week=6, group="fcs"),
    )
    boards = {(6, GROUP_FCS): tex_oklahoma()}
    app = CfbApp(client=WeekClient(boards), config=config)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, 1)
        assert app.glyphs.name == "unicode"
        assert app.scheduler.intervals == config.poll
        assert (app.scheduler.week, app.scheduler.group) == (6, GROUP_FCS)


async def test_explicit_arguments_beat_the_config():
    config = Config(view=ViewConfig(glyph_set="unicode", week=6, group="fcs"))
    app = CfbApp(client=WeekClient({}), config=config, glyph_set="ascii", week=3, group=GROUP_FBS)
    assert (app.glyphs.name, app.scheduler.week, app.scheduler.group) == ("ascii", 3, GROUP_FBS)


async def test_config_warnings_are_shown_to_the_user():
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): pregame()}), warnings=("poll.live should be positive",))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert any("poll.live" in n.message for n in app._notifications)


# --- favorites --------------------------------------------------------------------


async def test_starring_a_team_saves_it_and_the_next_run_shows_it_first(tmp_path):
    path = tmp_path / "cfbtui" / "config.toml"
    board = pregame()
    last = max(board.games, key=lambda g: sort_key(g))
    client = WeekClient({(None, GROUP_FBS): board})
    app = CfbApp(client=client, config=Config(), config_path=path, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        assert not path.exists(), "nothing is written until the first change"
        app.query_one(ScoreGrid).card_for(last.id).focus()
        await pilot.press("1")
        await pilot.pause()
        assert app.query_one(ScoreGrid).card_for(last.id).model.rows[0].left[2] == app.glyphs.favorite
        assert ids(app)[0] == last.id, "the starred game floats to the top"
    saved = load_config(path).config
    assert saved.favorites.team_ids == (last.away.id,)

    app = CfbApp(client=client, config=saved, config_path=path, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        assert ids(app)[0] == last.id
        await pilot.press("home")  # nothing focused; star keys must not crash
    # unstar again
    async with CfbApp(client=client, config=saved, config_path=path, glyph_set="ascii").run_test(size=SIZE) as pilot:
        app2 = pilot.app
        await settle(pilot, app2, len(board.games))
        app2.query_one(ScoreGrid).card_for(last.id).focus()
        await pilot.press("1")
        await pilot.pause()
    assert load_config(path).config.favorites.team_ids == ()


async def test_star_keys_without_a_focused_card_say_so_and_do_nothing(tmp_path):
    path = tmp_path / "config.toml"
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): pregame()}), config_path=path, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(pregame().games))
        app.set_focus(None)
        await pilot.press("1")
        await pilot.pause()
        assert not path.exists()
        assert any("Focus a card" in n.message for n in app._notifications)


async def test_no_config_keeps_the_star_for_the_run_and_says_it_is_not_saved():
    board = pregame()
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): board}), config_path=None, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        card = app.query(GameCard).last()
        card.focus()
        await pilot.press("2")
        await pilot.pause()
        assert card.game.home.id in app.favorites
        assert any("not saved" in n.message for n in app._notifications)


async def test_an_unwritable_config_path_is_reported_not_fatal(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): pregame()}), config_path=blocker / "config.toml", glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(pregame().games))
        app.query(GameCard).first().focus()
        await pilot.press("1")
        await pilot.pause()
        assert any("could not save" in n.message for n in app._notifications)


async def test_an_abbreviation_favorite_from_the_file_resolves_once_the_board_arrives():
    board = pregame()
    target = board.games[-1].home
    config = Config(favorites=FavoritesConfig((), (target.abbreviation,)))
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): board}), config=config, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        assert target.id in app.favorites
        assert target.id in {t for c in app.query(GameCard)[:1] for t in (c.game.away.id, c.game.home.id)}


def test_favorites_sort_first_then_by_the_usual_order():
    games = list(pregame().games)
    pick = games[-1]
    ordered = sorted(games, key=lambda g: sort_key(g, frozenset({pick.home.id})))
    assert ordered[0].id == pick.id
    assert [g.id for g in ordered[1:]] == [g.id for g in sorted(games, key=sort_key) if g.id != pick.id]


def test_a_favorite_event_is_marked_and_reversed_in_the_ticker():
    from cfbtui.ui.glyphs import get

    glyphs = get("ascii")
    event = _started(tex_oklahoma())
    plain = format_event(event, glyphs)
    starred = format_event(event, glyphs, favorites=frozenset({event.game.away.id}))
    assert glyphs.favorite not in plain.plain
    assert starred.plain.startswith(f"{glyphs.favorite} ")
    assert "reverse" in str(starred.spans[-1].style)


# --- focus ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "count", "cols", "key", "expected"),
    [
        (0, 7, 3, "left", 0),
        (4, 7, 3, "left", 3),
        (4, 7, 3, "right", 5),
        (6, 7, 3, "right", 6),
        (4, 7, 3, "up", 1),
        (1, 7, 3, "up", 1),
        (1, 7, 3, "down", 4),
        (5, 7, 3, "down", 6),  # short last row: land on the final card
        (6, 7, 3, "down", 6),
        (2, 7, 1, "down", 3),
        (0, 0, 3, "down", 0),
    ],
)
def test_next_index_clamps_and_handles_a_short_last_row(index, count, cols, key, expected):
    assert next_index(index, count, cols, key) == expected


async def test_arrow_keys_walk_the_cards_and_follow_a_reflow():
    board = pregame()
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): board}), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        grid = app.query_one(ScoreGrid)
        assert grid.focused_card is None
        await pilot.press("down")
        assert grid.focused_card is grid.cards[0], "the first arrow lands on the first card"
        await pilot.press("right")
        assert grid.focused_card is grid.cards[1]
        columns = grid.columns
        assert columns > 1
        await pilot.press("down")
        assert grid.focused_card is grid.cards[1 + columns]
        await pilot.press("up", "left")
        assert grid.focused_card is grid.cards[0]
        await pilot.resize_terminal(40, 44)  # one column now
        await pilot.pause(0.1)
        assert grid.columns == 1
        await pilot.press("down")
        assert grid.focused_card is grid.cards[1]
        await pilot.press("right")
        assert grid.focused_card is grid.cards[2]


async def test_focus_stays_on_the_game_when_the_order_changes():
    board = pregame()
    app = CfbApp(client=WeekClient({(None, GROUP_FBS): board}), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        grid = app.query_one(ScoreGrid)
        chosen = grid.cards[-1]
        chosen.focus()
        app.config = replace(app.config, favorites=FavoritesConfig((chosen.game.home.id,), ()))
        app.favorites = frozenset({chosen.game.home.id})
        app._repaint_grid()
        await pilot.pause(0.2)
        assert grid.cards[0] is chosen and grid.focused_card is chosen


# --- smaller carried-over fixes ----------------------------------------------------


def test_a_far_off_kickoff_shows_its_date_but_this_weeks_does_not():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    soon = datetime(2026, 10, 16, 16, 0, tzinfo=UTC)
    far = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
    assert kickoff_text(soon, now) == "Fri 12:00 PM ET"
    assert kickoff_text(far, now) == "Sat Oct 24 12:00 PM ET"
    assert kickoff_text(far) == "Sat 12:00 PM ET", "without a clock the old behavior stands"
    assert kickoff_text(now + timedelta(days=5, hours=1), now).count("Oct") == 1
    day_one = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    assert kickoff_text(day_one, now) == "Sun Nov 1 3:00 PM ET", "no leading zero on the day"


def test_a_game_that_cannot_be_diffed_does_not_cost_the_others_their_events():
    from cfbtui.state.store import GameStore

    before = load_game("pairs/touchdown_before.json")
    after = load_game("pairs/touchdown_after.json")
    other_before = replace(before, id="other-1")
    other_after = replace(after, id="other-1")
    store = GameStore()
    store.apply([before, other_before])
    original = store._diff
    calls = []

    def flaky(prev, cur):
        calls.append(cur.id)
        if cur.id == before.id:
            raise ValueError("bad payload")
        return original(prev, cur)

    store._diff = flaky
    events = store.apply([after, other_after])
    assert events, "the healthy game still reported its touchdown"
    assert all(e.game.id == "other-1" for e in events)
    assert [gid for gid, _ in store.last_errors] == [before.id]
    assert store._seen[before.id] is before, "the failed game keeps its old snapshot and is diffed again next time"
    assert {g.id for g in store.games} == {before.id, "other-1"}
    store._diff = original
    again = store.apply([after, other_after])
    assert any(e.game.id == before.id for e in again) and store.last_errors == []


async def test_saving_a_favorite_does_not_persist_flag_overrides(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(view=ViewConfig(glyph_set="emoji", week=None, group="fbs")), path)
    loaded = load_config(path).config
    flags = replace(loaded, view=replace(loaded.view, glyph_set="ascii", week=7))
    app = CfbApp(client=WeekClient({(7, GROUP_FBS): pregame()}), config=flags, file_config=loaded, config_path=path)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(pregame().games))
        app.query(GameCard).first().focus()
        await pilot.press("1")
        await pilot.pause()
    saved = load_config(path).config
    assert saved.view == loaded.view and len(saved.favorites.team_ids) == 1


def test_integer_team_ids_in_the_file_are_accepted():
    from cfbtui.config import parse_config

    cfg, warnings = parse_config({"favorites": {"team_ids": [251, "201"]}})
    assert cfg.favorites.team_ids == ("251", "201") and warnings == []
