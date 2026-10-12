"""GameCard: the pure card model in each state, the Rich renderer, and the widget's classes."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO

import pytest
from rich.console import Console
from textual.app import App, ComposeResult

from cfbtui.espn.models import Status
from cfbtui.state.upset import UpsetRule
from cfbtui.ui import glyphs as g
from cfbtui.ui.labels import kickoff_text, status_text
from cfbtui.ui.widgets.game_card import (
    GameCard,
    build_card,
    render_card,
)
from tests.fakes import load_board, load_game

ASCII = g.get("ascii")
WIDTH = 34


def lines(model, width: int = WIDTH) -> list[str]:
    return [line.rstrip() for line in model.lines(width)]


def card(path: str, *, rule: UpsetRule | None = None, glyphs=ASCII, **kw):
    game = load_game(path)
    verdict = (rule or UpsetRule()).evaluate(game)
    return game, build_card(game, glyphs, verdict=verdict, **kw)


# --- the five states ---------------------------------------------------------------


def test_pregame_card_shows_kickoff_in_eastern_and_the_odds():
    game = load_board("scoreboard_week7_pregame.json").games[0]
    model = build_card(game, ASCII)
    assert lines(model) == [
        "       DEL   2-3",
        "       MTSU  2-3",
        "- Tue 7:00 PM ET          DEL -1.5",
    ]
    assert model.title == ""
    assert model.classes == ("pregame",)


def test_live_card_shows_possession_timeouts_clock_and_down_and_distance():
    _, model = card("pairs/touchdown_after.json")
    assert lines(model) == [
        "    #1 TEX   4-1          ooo  14",
        " >     OU    3-2          ooo   7",
        "* Q2 10:09       1st & 10 at OU 25",
    ]
    assert model.classes == ("live",)
    assert model.rows[0].bold and not model.rows[1].bold, "the leader is bold"


def test_red_zone_card_gets_a_title_and_class():
    _, model = card("pairs/red_zone_after.json")
    assert model.title == "!! RED ZONE"
    assert model.classes == ("redzone", "live")
    assert lines(model)[2] == "* Q3 10:20      1st & 10 at TEX 17"


def test_upset_watch_card_gets_a_title_and_class():
    _, model = card("pairs/ranked_upset_watch_after.json")
    assert model.title == "? UPSET WATCH"
    assert model.classes == ("upset", "live")
    assert lines(model)[:2] == [
        " >  #5 TEX   4-1          ooo  17",
        "   #12 OU    3-2          ooo  24",
    ]


def test_final_card_dims_the_loser_and_calls_the_upset():
    # Fixture: #1 TEX lost to unranked OU, a confirmed upset.
    _, model = card("pairs/final_after.json")
    assert lines(model) == [
        "    #1 TEX   4-1               24",
        "       OU    3-2               27",
        "F Final",
    ]
    assert model.title == "!!! UPSET"
    assert model.classes == ("upset", "final")
    assert model.rows[1].bold and model.rows[0].dim


def test_final_without_an_upset_has_no_title():
    game = load_game("pairs/final_after.json")
    model = build_card(game, ASCII, verdict=None)
    assert model.title == "" and model.classes == ("final",)


def test_halftime_card():
    _, model = card("pairs/halftime_after.json")
    assert lines(model)[2].startswith("H Halftime")


# --- glyph sets --------------------------------------------------------------------


@pytest.mark.parametrize("name", g.GLYPH_SET_NAMES)
def test_every_glyph_set_builds_every_state(name):
    table = g.get(name)
    for path in (
        "pairs/touchdown_after.json",
        "pairs/red_zone_after.json",
        "pairs/ranked_upset_watch_after.json",
        "pairs/final_after.json",
        "pairs/halftime_after.json",
        "pairs/game_start_before.json",
    ):
        game = load_game(path)
        model = build_card(game, table, verdict=UpsetRule().evaluate(game))
        assert all(model.lines())
    assert table.live in build_card(load_game("pairs/touchdown_after.json"), table).status


def test_icons_in_the_card_come_from_the_table():
    game = load_game("pairs/red_zone_after.json")
    for name in g.GLYPH_SET_NAMES:
        table = g.get(name)
        assert table.red_zone in build_card(game, table).title


# --- status text -------------------------------------------------------------------


def test_kickoff_text_is_eastern_without_a_leading_zero():
    when = datetime(2026, 10, 17, 16, 0, tzinfo=UTC)  # noon EDT
    assert kickoff_text(when) == "Sat 12:00 PM ET"
    assert kickoff_text(datetime(2026, 10, 17, 13, 30, tzinfo=UTC)) == "Sat 9:30 AM ET"
    # Daylight time ends 2026-11-01; after that Eastern is UTC-5.
    assert kickoff_text(datetime(2026, 11, 7, 17, 0, tzinfo=UTC)) == "Sat 12:00 PM ET"


def test_status_text_variants():
    base = load_game("pairs/touchdown_after.json")

    def with_status(**kw):
        return replace(base, status=replace(base.status, **kw))

    assert status_text(with_status(period=5, clock="3:00"), ASCII) == "* OT 3:00"
    assert status_text(with_status(period=6, clock="3:00"), ASCII) == "* OT2 3:00"
    delayed = with_status(name="STATUS_DELAYED", short_detail="Delayed")
    assert status_text(delayed, ASCII) == "* Delayed"
    end = with_status(name="STATUS_END_PERIOD", short_detail="End of 2nd")
    assert status_text(end, ASCII) == "* End of 2nd"
    final_ot = replace(
        base,
        status=Status(state=base.status.state.__class__("post"), name="STATUS_FINAL", completed=True, period=5),
    )
    assert status_text(final_ot, ASCII) == "F Final/OT"
    postponed = replace(
        base,
        status=Status(state=base.status.state.__class__("post"), name="STATUS_POSTPONED", short_detail="Postponed"),
    )
    assert status_text(postponed, ASCII) == "F Postponed"


def test_unknown_data_does_not_crash_the_card():
    game = load_game("pairs/touchdown_after.json")
    bare = replace(game, situation=None, odds=None)
    model = build_card(bare, ASCII)
    assert len(model.lines()) == 3


# --- renderer ----------------------------------------------------------------------


def _render(model, width: int = WIDTH) -> list[str]:
    out = StringIO()
    Console(file=out, width=width, color_system=None, force_terminal=False).print(render_card(model))
    return [line.rstrip() for line in out.getvalue().splitlines()]


@pytest.mark.parametrize(
    "path",
    ["pairs/touchdown_after.json", "pairs/final_after.json", "pairs/red_zone_after.json"],
)
def test_renderer_matches_the_model_text(path):
    _, model = card(path)
    assert [" ".join(line.split()) for line in _render(model)] == [" ".join(line.split()) for line in lines(model)]


def test_flash_marks_only_the_scoring_side():
    game = load_game("pairs/touchdown_after.json")
    model = build_card(game, ASCII, flash_team_id=game.away.id)
    assert [row.flash for row in model.rows] == [True, False]
    assert "flash" in model.classes


# --- the widget --------------------------------------------------------------------


class _Host(App[None]):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget

    def compose(self) -> ComposeResult:
        yield self.widget


async def test_widget_carries_title_and_state_classes():
    game = load_game("pairs/ranked_upset_watch_after.json")
    widget = GameCard(game, ASCII, verdict=UpsetRule().evaluate(game))
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        assert widget.border_title == "? UPSET WATCH"
        assert widget.has_class("live") and widget.has_class("upset")
        assert not widget.has_class("final")


async def test_widget_repaints_on_new_game_and_dims_when_old():
    before, after = load_game("pairs/touchdown_before.json"), load_game("pairs/touchdown_after.json")
    widget = GameCard(before, ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        assert widget.model is not None and widget.model.rows[0].score.strip() == "7"
        widget.show(after, ASCII, None)
        assert widget.model.rows[0].score.strip() == "14"
        assert not widget.has_class("old")
        widget.set_data_old(True)
        assert widget.has_class("old")
        widget.set_data_old(False)
        assert not widget.has_class("old")


async def test_widget_flash_sets_then_clears_the_class():
    game = load_game("pairs/touchdown_after.json")
    widget = GameCard(game, ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        widget.flash(game.away.id)
        assert widget.has_class("flash")
        widget._end_flash()
        assert not widget.has_class("flash")


async def test_widget_actually_paints_each_team_color_on_screen():
    """The model carries colors; this checks they survive Rich and Textual into the rendered strips."""
    game = load_game("pairs/touchdown_after.json")
    widget = GameCard(game, ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        for y, row in enumerate(widget.model.rows):
            strip = widget.render_line(y)
            backgrounds = {str(seg.style.bgcolor.name) for seg in strip if seg.style and seg.style.bgcolor}
            assert backgrounds == {row.background}, f"row {y} painted {backgrounds}, wanted {row.background}"


async def test_an_unchanged_game_is_not_repainted():
    game = load_game("pairs/touchdown_after.json")
    widget = GameCard(game, ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        first = widget.model
        widget.show(load_game("pairs/touchdown_after.json"), ASCII, None)  # equal, but a new object
        assert widget.model is first
        widget.show(load_game("pairs/touchdown_before.json"), ASCII, None)
        assert widget.model is not first


async def test_flash_before_mount_starts_its_timer_on_mount_and_restarts_cleanly():
    game = load_game("pairs/touchdown_after.json")
    widget = GameCard(game, ASCII)
    widget.flash(game.away.id)  # not attached yet: must not raise
    assert widget.has_class("flash")
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        first = widget._flash_timer
        assert first is not None
        widget.flash(game.home.id)
        assert widget._flash_timer is not first, "a second flash restarts the timer"
