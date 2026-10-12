"""Ticker lines: one expected line per event kind, plus the widget's cap and glyph redraw."""
from __future__ import annotations

from datetime import datetime

import pytest
from textual.app import App, ComposeResult

from cfbtui.state.events import StatusChanged
from cfbtui.state.store import GameStore
from cfbtui.ui import glyphs as g
from cfbtui.ui.widgets.ticker import CAP, Ticker, format_event
from tests.fakes import load_game

ASCII = g.get("ascii")


def events_for(kind: str):
    store = GameStore()
    store.apply([load_game(f"pairs/{kind}_before.json")])
    return store.apply([load_game(f"pairs/{kind}_after.json")])


def plain(kind: str, index: int = 0) -> str:
    return format_event(events_for(kind)[index], ASCII).plain


def test_touchdown_line_has_icon_label_team_points_score_clock_and_play_text():
    assert plain("touchdown") == (
        "# TD TEX +7  TEX 14 - OU 7  Q2 10:09  "
        "Ryan Wingo 34 Yd pass from Arch Manning (Gianni Spetic Kick)"
    )


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [
        ("field_goal", "^ FG TEX +3  TEX 17 - OU 7  Q2 0:12"),
        ("safety", "! SAFETY OU +2  TEX 17 - OU 9  Q3 7:50"),
        ("two_point", "= 2PT OU +2  TEX 17 - OU 17  Q4 14:48"),
        ("pat", "+ PAT TEX +1  TEX 24 - OU 24  Q4 6:32"),
    ],
)
def test_each_score_kind_uses_its_label_and_icon(kind, prefix):
    assert plain(kind).startswith(prefix)


def test_inferred_scores_carry_a_question_mark_and_no_play_text():
    assert plain("multi_score", 0) == "# TD? TEX +7  TEX 17 - OU 7  Q2 0:12"
    assert plain("multi_score", 1) == "^ FG? TEX +3  TEX 17 - OU 7  Q2 0:12"


def test_status_events():
    assert plain("game_start") == "> KICKOFF TEX @ OU  TEX 0 - OU 0  Q1 15:00"
    assert plain("period_change") == ">> Q2 TEX @ OU  TEX 7 - OU 0"
    assert plain("halftime") == "H HALFTIME TEX @ OU  TEX 17 - OU 7"
    assert plain("final", 0) == "F FINAL TEX 24 - OU 27"


def test_situation_and_upset_events():
    assert plain("red_zone") == "!! RED ZONE OU at TEX 17  TEX 17 - OU 7"
    assert plain("upset_watch", 1) == "? UPSET WATCH OU leads #1 TEX  TEX 17 - OU 24"
    assert plain("ranked_upset_watch", 1) == "? UPSET WATCH #12 OU leads #5 TEX  TEX 17 - OU 24"
    assert plain("final", 1) == "!!! UPSET OU beats #1 TEX  TEX 24 - OU 27"


def test_correction_and_status_change():
    assert plain("score_correction") == "< CORRECTION TEX 20 to 17  TEX 17 - OU 7"
    game = load_game("pairs/touchdown_after.json")
    line = format_event(StatusChanged(game, "STATUS_IN_PROGRESS", "STATUS_DELAYED"), ASCII).plain
    assert line == "~ TEX @ OU  In Progress to Delayed"


def test_stamp_prefix():
    event = events_for("halftime")[0]
    line = format_event(event, ASCII, stamp=datetime(2026, 10, 17, 14, 5)).plain
    assert line.startswith("14:05 H HALFTIME")


def test_lines_never_use_str_of_the_event():
    for kind in ("touchdown", "halftime", "red_zone"):
        for event in events_for(kind):
            assert format_event(event, ASCII).plain != str(event)


@pytest.mark.parametrize("name", g.GLYPH_SET_NAMES)
def test_icons_come_from_the_active_set(name):
    table = g.get(name)
    event = events_for("touchdown")[0]
    assert format_event(event, table).plain.startswith(table.touchdown)


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield Ticker(ASCII, id="ticker")


async def test_widget_appends_in_order_caps_and_redraws_on_glyph_change():
    async with _Host().run_test(size=(100, 20)) as pilot:
        ticker = pilot.app.query_one(Ticker)
        td, half = events_for("touchdown")[0], events_for("halftime")[0]
        ticker.add_events([td, half])
        await pilot.pause()
        assert ticker.entry_count == 2
        assert len(ticker.lines) >= 2
        first = "".join(seg.text for seg in ticker.lines[0])
        assert "TD TEX" in first
        ticker.set_glyphs(g.get("unicode"))
        await pilot.pause()
        assert "★" in "".join(seg.text for seg in ticker.lines[0])
        ticker.add_events([half] * (CAP + 25))
        await pilot.pause()
        assert ticker.entry_count == CAP
