"""Card pulses: which events pulse, the cool-down, the quiet first poll, and the widget class lifecycle."""
from __future__ import annotations

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from cfbtui.app import CfbApp
from cfbtui.state.events import GameFinal, PeriodChanged, RedZone, UpsetWatch
from cfbtui.ui import glyphs as g
from cfbtui.ui.pulse import PulseGate, pulse_kind
from cfbtui.ui.widgets.game_card import PULSE_CYCLES, GameCard
from tests.fakes import FakeClient, load_board, load_game
from tests.test_app_smoke import FAST, SIZE, wait_for

ASCII = g.get("ascii")


def test_events_map_to_pulse_kinds():
    game = load_game("pairs/touchdown_after.json")
    assert pulse_kind(RedZone(game, None)) == "redzone"
    assert pulse_kind(UpsetWatch(game, game.away, game.home)) == "upset"
    assert pulse_kind(PeriodChanged(game, 5)) == "overtime"
    assert pulse_kind(GameFinal(game, game.away, game.home)) == "final"


def test_regulation_periods_and_scores_do_not_pulse():
    game = load_game("pairs/touchdown_after.json")
    assert pulse_kind(PeriodChanged(game, 4)) is None


def test_the_cool_down_is_per_game_and_kind():
    now = [0.0]
    gate = PulseGate(cooldown=60, clock=lambda: now[0])
    assert gate.allow("1", "redzone")
    assert not gate.allow("1", "redzone"), "a bounce in and out of the red zone"
    assert gate.allow("1", "upset") and gate.allow("2", "redzone")
    now[0] = 61
    assert gate.allow("1", "redzone")


class _Host(App[None]):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget

    def compose(self) -> ComposeResult:
        yield self.widget


async def test_pulse_sets_the_classes_then_clears_them_when_it_ends():
    widget = GameCard(load_game("pairs/touchdown_after.json"), ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        widget.pulse("redzone")
        assert widget.has_class("pulsing") and widget.has_class("pulse-redzone") and widget.has_class("pulse-hi")
        widget._pulse_step()
        assert not widget.has_class("pulse-hi"), "the breath dims"
        widget._pulse_step()
        assert widget.has_class("pulse-hi")
        for _ in range(PULSE_CYCLES * 2):
            widget._pulse_step()
        assert not any(c.startswith("pulse") for c in widget.classes)
        assert widget._pulse_timer is None


async def test_a_second_pulse_restarts_instead_of_stacking():
    widget = GameCard(load_game("pairs/touchdown_after.json"), ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        widget.pulse("redzone")
        first = widget._pulse_timer
        widget._pulse_step()
        widget.pulse("overtime")
        assert widget._pulse_timer is not first
        assert widget.has_class("pulse-overtime") and not widget.has_class("pulse-redzone")
        assert widget._pulse_steps == PULSE_CYCLES * 2


async def test_pulse_coexists_with_flash_and_old_dimming():
    widget = GameCard(load_game("pairs/touchdown_after.json"), ASCII)
    async with _Host(widget).run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        widget.pulse("final")
        widget.flash(widget.game.away.id)
        widget.set_data_old(True)
        assert widget.has_class("pulsing") and widget.has_class("flash") and widget.has_class("old")
        widget._end_flash()
        assert widget.has_class("pulsing") and widget.has_class("old")


def test_an_unknown_kind_is_rejected():
    widget = GameCard(load_game("pairs/touchdown_after.json"), ASCII)
    with pytest.raises(ValueError):
        widget.pulse("sparkle")


def _app(before: str, after: str) -> CfbApp:
    client = FakeClient(load_board(f"pairs/{before}.json"), load_board(f"pairs/{after}.json"))
    return CfbApp(client=client, intervals=FAST, glyph_set="ascii")


async def test_a_game_going_final_pulses_its_card():
    app = _app("final_before", "final_after")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(GameCard).has_class("pulse-final"))


async def test_a_red_zone_entry_pulses_its_card():
    app = _app("red_zone_before", "red_zone_after")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(GameCard).has_class("pulse-redzone"))


async def test_alerts_off_means_no_pulse():
    app = _app("final_before", "final_after")
    app.config = replace(app.config, alerts=replace(app.config.alerts, enabled=False))
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.query_one(GameCard).game.is_final)
        await pilot.pause(0.2)
        assert not app.query_one(GameCard).has_class("pulsing")


async def test_the_quiet_first_poll_does_not_pulse():
    def app(quiet: bool) -> CfbApp:
        a = CfbApp(client=FakeClient(load_board("pairs/red_zone_after.json")), intervals=FAST, glyph_set="ascii")
        a._quiet_first_poll = quiet
        return a

    loud = app(False)
    async with loud.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: loud.query_one(GameCard).has_class("pulse-redzone"))
    quiet = app(True)
    async with quiet.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: len(quiet.query(GameCard)) > 0)
        await pilot.pause(0.3)
        assert not quiet.query_one(GameCard).has_class("pulsing")
