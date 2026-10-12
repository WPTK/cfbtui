"""The Textual application: a score grid, a ticker and a status bar fed by a poll scheduler.

The scheduler runs in a worker and hands each :class:`~cfbtui.poll.PollResult`
back as a :class:`PollUpdated` message. Everything the user sees is repainted
from the store's current games, so a failed poll simply leaves the last good
cards on screen while the status bar says how old they are.

Keys: ``q`` quit, ``r`` refresh now, ``g`` cycle the glyph set.
"""
from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Footer

from cfbtui.espn.client import GROUP_FBS, EspnClient
from cfbtui.poll import PollIntervals, PollResult, PollScheduler, ScoreboardSource
from cfbtui.state.events import Scored
from cfbtui.state.store import GameStore
from cfbtui.ui import glyphs as glyph_tables
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.widgets.score_grid import ScoreGrid
from cfbtui.ui.widgets.status_bar import StatusBar, StatusView
from cfbtui.ui.widgets.ticker import Ticker


class PollUpdated(Message):
    """A poll finished, good or bad. Carries the scheduler's result."""

    def __init__(self, result: PollResult) -> None:
        super().__init__()
        self.result = result


class CfbApp(App[None]):
    TITLE = "cfbtui"
    CSS_PATH = "ui/app.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("g", "cycle_glyphs", "Glyphs"),
    ]

    def __init__(
        self,
        *,
        client: ScoreboardSource | None = None,
        intervals: PollIntervals | None = None,
        glyph_set: str | None = None,
        week: int | None = None,
        group: int = GROUP_FBS,
    ) -> None:
        super().__init__()
        self._owns_client = client is None
        self.client: ScoreboardSource = client if client is not None else EspnClient()
        self.glyphs: Glyphs = glyph_tables.get(glyph_set)
        self.store = GameStore()
        self.scheduler = PollScheduler(
            self.client,
            self.store,
            intervals=intervals,
            week=week,
            group=group,
            on_result=lambda result: self.post_message(PollUpdated(result)),
        )
        self.last_result: PollResult | None = None

    def compose(self) -> ComposeResult:
        yield ScoreGrid(id="grid")
        yield Ticker(self.glyphs, id="ticker")
        yield StatusBar(self.glyphs, id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(ScoreGrid).set_message(f"{self.glyphs.loading} Loading the scoreboard")
        self.run_worker(self.scheduler.run(), name="poll", group="poll", exclusive=True)
        self.set_interval(1.0, self._tick)
        self._tick()

    async def on_unmount(self) -> None:
        self.scheduler.stop()
        if self._owns_client and isinstance(self.client, EspnClient):
            await self.client.aclose()

    # --- poll results ----------------------------------------------------------

    def on_poll_updated(self, message: PollUpdated) -> None:
        result = message.result
        self.last_result = result
        grid = self.query_one(ScoreGrid)
        if result.ok:
            grid.update_games(self.store.games, self.glyphs, self.store.rule, data_old=False)
            self.query_one(Ticker).add_events(result.events, stamp=datetime.now())
            for event in result.events:
                if isinstance(event, Scored):
                    grid.flash(event.game_id, event.team.id)
        elif self.scheduler.scoreboard is None:
            grid.set_message(f"{self.glyphs.error} Could not reach ESPN. Retrying. ({result.error})")
        self._tick()

    def _tick(self) -> None:
        """Once a second: refresh the status line and dim the cards if the data has gone old."""
        freshness = self.scheduler.freshness()
        board = self.scheduler.scoreboard
        view = StatusView(
            freshness=freshness,
            week=board.week if board else None,
            live=len(self.store.live),
            total=len(self.store),
            next_in=self.scheduler.seconds_until_next(),
            polling=self.scheduler.polling,
            glyph_set=self.glyphs.name,
        )
        self.query_one(StatusBar).show(view, self.glyphs)
        self.query_one(ScoreGrid).set_data_old(freshness.data_old)

    # --- actions ---------------------------------------------------------------

    def action_refresh(self) -> None:
        self.scheduler.refresh()

    def action_cycle_glyphs(self) -> None:
        self.glyphs = glyph_tables.get(glyph_tables.next_name(self.glyphs.name))
        self.query_one(Ticker).set_glyphs(self.glyphs)
        grid = self.query_one(ScoreGrid)
        if len(self.store):
            data_old = self.scheduler.freshness().data_old
            grid.update_games(self.store.games, self.glyphs, self.store.rule, data_old=data_old)
        self._tick()
        self.notify(f"Glyph set: {self.glyphs.name}", timeout=2)


def run() -> None:
    CfbApp().run()


if __name__ == "__main__":
    run()
