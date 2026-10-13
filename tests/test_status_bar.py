"""The status line: pure formatting for each freshness state, then the widget's classes."""
from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult

from cfbtui import __version__
from cfbtui.poll import Freshness, FreshnessState
from cfbtui.ui import glyphs as g
from cfbtui.ui.widgets.status_bar import StatusBar, StatusView, format_status

ASCII = g.get("ascii")
NOW = datetime(2026, 10, 17, 14, 5, 9)


def view(**kw) -> StatusView:
    return StatusView(**kw)


def test_loading():
    text = format_status(view(), ASCII)
    assert text.startswith("... loading")
    assert f"v{__version__}" in text


def test_fresh_shows_age_countdown_week_and_live_count():
    f = Freshness(FreshnessState.FRESH, age=12.4, stale_after=50)
    text = format_status(view(freshness=f, week=7, live=3, total=62, next_in=8.2, glyph_set="ascii"), ASCII, NOW)
    sep = ASCII.sep
    assert text == sep.join(
        ["ok updated 12s ago", "next 8s", "Week 7", "3 live of 62", f"v{__version__}", "glyphs: ascii", "Sat 14:05:09"]
    )


def test_polling_replaces_the_countdown():
    f = Freshness(FreshnessState.FRESH, age=19, stale_after=50)
    text = format_status(view(freshness=f, polling=True, next_in=None), ASCII)
    assert "@ polling" in text and "next" not in text


def test_a_slow_countdown_says_why():
    f = Freshness(FreshnessState.FRESH, age=19, stale_after=300)
    assert "next 1m40s (away)" in format_status(view(freshness=f, next_in=100, away=True), ASCII)
    assert "(away)" not in format_status(view(freshness=f, next_in=100), ASCII)


def test_stale_says_so_with_the_age():
    f = Freshness(FreshnessState.STALE, age=95, stale_after=50)
    assert format_status(view(freshness=f), ASCII).startswith("~ STALE 1m35s old")


def test_error_with_old_data_names_the_age_and_failure_count():
    f = Freshness(FreshnessState.ERROR, age=64, stale_after=50, failures=3, error="EspnNetworkError: down")
    text = format_status(view(freshness=f, week=7, live=1, total=10, next_in=40), ASCII)
    assert text.startswith("x ERROR showing data 1m04s old")
    assert "3 failed polls" in text
    assert "Week 7" in text


def test_error_before_any_data():
    f = Freshness(FreshnessState.ERROR, age=None, failures=1)
    assert format_status(view(freshness=f), ASCII).startswith("x ERROR no data yet")


def test_no_games_hides_the_live_count():
    f = Freshness(FreshnessState.FRESH, age=1, stale_after=50)
    assert "live of" not in format_status(view(freshness=f), ASCII)


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield StatusBar(ASCII)


async def test_widget_text_and_state_class_follow_the_view():
    async with _Host().run_test(size=(120, 5)) as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.show(view(freshness=Freshness(FreshnessState.FRESH, age=2, stale_after=50)), now=NOW)
        assert bar.has_class("fresh") and not bar.has_class("error")
        assert "updated 2s ago" in bar.text
        bar.show(view(freshness=Freshness(FreshnessState.ERROR, age=70, stale_after=50, failures=2)), now=NOW)
        assert bar.has_class("error") and not bar.has_class("fresh")
        assert "ERROR" in bar.text
        bar.show(view(freshness=Freshness(FreshnessState.STALE, age=70, stale_after=50)), g.get("unicode"), NOW)
        assert bar.has_class("stale")
        assert g.get("unicode").stale in bar.text
