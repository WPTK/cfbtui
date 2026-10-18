"""The footer and status line fit 60, 80 and 120 columns; `?` lists every key."""
from __future__ import annotations

from datetime import datetime

import pytest
from textual.binding import Binding
from textual.widgets import Footer
from textual.widgets._footer import FooterKey

from cfbtui import __version__
from cfbtui.app import CfbApp
from cfbtui.poll import Freshness, FreshnessState
from cfbtui.ui import glyphs as g
from cfbtui.ui.screens.help import HelpScreen, help_rows
from cfbtui.ui.widgets.status_bar import StatusBar, StatusView, fit_segments, format_status
from tests.fakes import FakeClient, load_board
from tests.test_app_smoke import wait_for

ASCII = g.get("ascii")
NOW = datetime(2026, 10, 17, 14, 5, 9)
FULL = StatusView(
    freshness=Freshness(FreshnessState.FRESH, age=12.4, stale_after=50),
    week=7, group="FBS", live=3, total=62, next_in=8.2, glyph_set="ascii", view_note="Live, SEC",
)


def test_fit_segments_without_a_width_keeps_everything():
    assert fit_segments([(0, "a"), (2, "b")], " | ", None) == "a | b"


def test_fit_segments_drops_the_highest_priority_number_first():
    parts = [(0, "health"), (3, "clock"), (1, "week"), (2, "version")]
    assert fit_segments(parts, " ", 100) == "health clock week version"
    assert fit_segments(parts, " ", 19) == "health week version"
    assert fit_segments(parts, " ", 11) == "health week"


def test_fit_segments_drops_the_rightmost_of_equals_and_never_the_last_one():
    assert fit_segments([(1, "aa"), (1, "bb"), (1, "cc")], "", 4) == "aabb"
    assert fit_segments([(0, "health")], " ", 2) == "health"


def test_clock_glyph_set_and_version_go_first():
    full = format_status(FULL, ASCII, NOW)
    assert "Sat 14:05:09" not in format_status(FULL, ASCII, NOW, len(full) - 1)
    no_clock = format_status(FULL, ASCII, NOW, len(full) - 1)
    no_glyphs = format_status(FULL, ASCII, NOW, len(no_clock) - 1)
    assert "glyphs" not in no_glyphs and "v" + __version__ in no_glyphs
    no_version = format_status(FULL, ASCII, NOW, len(no_glyphs) - 1)
    assert "v" + __version__ not in no_version and "Week 7" in no_version and "ok updated" in no_version


@pytest.mark.parametrize("width", [60, 80, 120])
def test_the_status_text_never_exceeds_its_width(width):
    for view in (FULL, StatusView(freshness=Freshness(FreshnessState.ERROR, age=64, stale_after=50, failures=3), week=7)):
        assert len(format_status(view, ASCII, NOW, width)) <= width


def test_help_rows_list_every_described_binding_and_esc():
    bindings = list(Binding.make_bindings(CfbApp.BINDINGS))
    rows = help_rows(bindings, lambda b: b.key)
    assert ("Esc", "Back from a screen") in rows
    assert len(rows) == len(bindings) + 1


@pytest.mark.parametrize("width", [60, 80, 120])
async def test_footer_and_status_fit_and_resize_reflows(width):
    app = CfbApp(client=FakeClient(load_board("scoreboard_week7_pregame.json")), glyph_set="ascii")
    async with app.run_test(size=(width, 30)) as pilot:
        await wait_for(pilot, lambda: "updated" in app.query_one(StatusBar).text)
        footer, status = app.query_one(Footer), app.query_one(StatusBar)
        await wait_for(pilot, lambda: len(footer.query(FooterKey)) >= 5)
        keys = list(footer.query(FooterKey))
        assert [k.key_display for k in keys][:2] == ["q", "?"] and len(keys) < 8  # the core set, not all 17
        assert any(k.key_display == "?" for k in keys)
        assert all(k.region.right <= footer.region.right for k in keys if k.region.width)
        assert len(status.text) <= width - 2
        assert "updated" in status.text
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert len(status.text) <= 58
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        assert "glyphs: ascii" in status.text


async def test_question_mark_opens_help_with_every_key_and_closes():
    app = CfbApp(client=FakeClient(load_board("scoreboard_week7_pregame.json")), glyph_set="ascii")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        descriptions = {d for _, d in app.screen.rows}
        assert {"Quit", "Prev week", "Copy all", "Conference", "Refresh"} <= descriptions
        await pilot.press("question_mark")
        assert not isinstance(app.screen, HelpScreen)
        await pilot.press("question_mark", "escape")
        assert len(app.screen_stack) == 1
