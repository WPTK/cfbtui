"""The Textual application: a score grid, a ticker and a status bar fed by a poll scheduler.

The scheduler runs in a worker and hands each :class:`~cfbtui.poll.PollResult`
back as a :class:`PollUpdated` message. Everything the user sees is repainted
from the store's current games, so a failed poll simply leaves the last good
cards on screen while the status bar says how old they are.

Keys: ``q`` quit, ``r`` refresh now, ``g`` cycle the glyph set, ``[`` and ``]``
previous and next week, ``t`` this week, ``f`` toggle FBS and FCS, arrow keys
move between cards, ``1`` and ``2`` star or unstar the focused card's away and
home team.

**Switching.** :meth:`CfbApp._switch` points the scheduler elsewhere, clears
the cards and the ticker, and shows a loading message. A poll that was already
in flight for the old view is dropped by the scheduler, and a
:class:`PollUpdated` that was already queued for it is dropped here by its
``generation``. The first board of the new view is shown but announces
nothing, so opening a week does not flood the ticker with kickoffs.

**Favorites** live in the config as team ids and are saved on every toggle.
A config that cannot be written (``--no-config``, a read-only directory) keeps
the change for this run and says so.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Footer

from cfbtui.config import MAX_WEEK, MIN_WEEK, Config, favorite_ids, save_config
from cfbtui.espn.client import GROUP_FBS, GROUP_FCS, EspnClient
from cfbtui.poll import PollIntervals, PollResult, PollScheduler, ScoreboardSource
from cfbtui.state.events import Scored
from cfbtui.state.store import GameStore
from cfbtui.ui import glyphs as glyph_tables
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.widgets.score_grid import ScoreGrid
from cfbtui.ui.widgets.status_bar import StatusBar, StatusView
from cfbtui.ui.widgets.ticker import Ticker

GROUP_NAMES = {GROUP_FBS: "FBS", GROUP_FCS: "FCS"}


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
        Binding("left_square_bracket", "week(-1)", "Prev week"),
        Binding("right_square_bracket", "week(1)", "Next week"),
        ("t", "this_week", "This week"),
        ("f", "toggle_group", "FBS/FCS"),
        Binding("1", "favorite('away')", "Star away"),
        Binding("2", "favorite('home')", "Star home"),
    ]

    def __init__(
        self,
        *,
        client: ScoreboardSource | None = None,
        intervals: PollIntervals | None = None,
        glyph_set: str | None = None,
        week: int | None = None,
        group: int | None = None,
        config: Config | None = None,
        file_config: Config | None = None,
        config_path: Path | None = None,
        warnings: tuple[str, ...] = (),
    ) -> None:
        """Explicit arguments win over ``config``, which wins over the built-in defaults.

        ``config_path`` is where favorites are saved; ``None`` means nowhere.
        """
        super().__init__()
        self.config = config if config is not None else Config()
        self.config_path = config_path
        self.file_config = file_config if file_config is not None else self.config  # what the file holds, without flags
        self.config_warnings = warnings
        view = self.config.view
        self._owns_client = client is None
        self.client: ScoreboardSource = client if client is not None else EspnClient()
        self.glyphs: Glyphs = glyph_tables.get(glyph_set if glyph_set is not None else view.glyph_set)
        self.store = GameStore()
        self.scheduler = PollScheduler(
            self.client,
            self.store,
            intervals=intervals if intervals is not None else self.config.poll,
            week=week if week is not None else view.week,
            group=group if group is not None else view.group_id,
            on_result=lambda result: self.post_message(PollUpdated(result)),
        )
        self.last_result: PollResult | None = None
        self.favorites: frozenset[str] = favorite_ids(self.config)
        self._quiet_first_poll = False

    def compose(self) -> ComposeResult:
        yield ScoreGrid(id="grid")
        yield Ticker(self.glyphs, self.favorites, id="ticker")
        yield StatusBar(self.glyphs, id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(ScoreGrid).set_message(f"{self.glyphs.loading} Loading the scoreboard")
        for warning in self.config_warnings:
            self.notify(warning, title="Config", severity="warning", timeout=10)
        self.run_worker(self.scheduler.run(), name="poll", group="poll", exclusive=True)
        self.set_interval(1.0, self._tick)
        self._tick()

    async def on_unmount(self) -> None:
        self.scheduler.stop()
        if self._owns_client and isinstance(self.client, EspnClient):
            await self.client.aclose()

    # --- poll results ----------------------------------------------------------

    def on_poll_updated(self, message: PollUpdated) -> None:
        try:
            self._show_result(message.result)
        except NoMatches:  # the screen is being torn down while a last poll lands
            pass

    def _show_result(self, result: PollResult) -> None:
        if result.generation != self.scheduler.generation:
            return  # queued before the user switched week or group
        self.last_result = result
        grid = self.query_one(ScoreGrid)
        quiet = self._quiet_first_poll and result.ok
        if quiet:
            self._quiet_first_poll = False
        if result.ok:
            self._refresh_favorites()
            grid.update_games(
                self.store.games, self.glyphs, self.store.rule, data_old=False, favorites=self.favorites
            )
            if not quiet:
                self.query_one(Ticker).add_events(result.events, stamp=datetime.now())
                for event in result.events:
                    if isinstance(event, Scored):
                        grid.flash(event.game_id, event.team.id)
        elif self.scheduler.scoreboard is None:
            grid.set_message(f"{self.glyphs.error} Could not reach ESPN. Retrying. ({result.error})")
        self._tick()

    def _tick(self) -> None:
        try:
            self._update_status()
        except NoMatches:  # the screen is being torn down
            pass

    def _update_status(self) -> None:
        """Once a second: refresh the status line and dim the cards if the data has gone old."""
        freshness = self.scheduler.freshness()
        board = self.scheduler.scoreboard
        week = board.week if board and board.week is not None else self.scheduler.week
        view = StatusView(
            freshness=freshness,
            week=week,
            group=GROUP_NAMES.get(self.scheduler.group, ""),
            live=len(self.store.live),
            total=len(self.store),
            next_in=self.scheduler.seconds_until_next(),
            polling=self.scheduler.polling,
            glyph_set=self.glyphs.name,
        )
        self.query_one(StatusBar).show(view, self.glyphs)
        self.query_one(ScoreGrid).set_data_old(freshness.data_old)

    # --- favorites -------------------------------------------------------------

    def _teams_seen(self) -> list[tuple[str, str]]:
        return [(t.id, t.abbreviation) for g in self.store.games for t in (g.away.team, g.home.team)]

    def _refresh_favorites(self) -> None:
        """Re-resolve abbreviations from the config against the teams now on the board."""
        favorites = favorite_ids(self.config, self._teams_seen())
        if favorites != self.favorites:
            self.favorites = favorites
            self.query_one(Ticker).set_favorites(favorites)

    def action_favorite(self, side: str) -> None:
        card = self.query_one(ScoreGrid).focused_card
        if card is None:
            self.notify("Focus a card with the arrow keys first.", timeout=3)
            return
        team = (card.game.away if side == "away" else card.game.home).team
        self.toggle_favorite(team.id, team.abbreviation)

    def toggle_favorite(self, team_id: str, abbreviation: str) -> None:
        """Star or unstar a team, save the config, and repaint. Unstarring drops its abbreviation too."""
        fav = self.config.favorites
        if team_id in self.favorites:
            ids = tuple(i for i in fav.team_ids if i != team_id)
            abbrs = tuple(a for a in fav.abbreviations if a != abbreviation.upper())
            message = f"Removed {abbreviation} from favorites"
        else:
            ids = (*fav.team_ids, team_id)
            abbrs = fav.abbreviations
            message = f"Added {abbreviation} to favorites"
        self.config = replace(self.config, favorites=replace(fav, team_ids=ids, abbreviations=abbrs))
        self.favorites = favorite_ids(self.config, self._teams_seen())
        self.query_one(Ticker).set_favorites(self.favorites)
        self._repaint_grid()
        self.notify(message + self._save(), timeout=3)

    def _save(self) -> str:
        if self.config_path is None:
            return " (not saved: --no-config)"
        try:
            # Save the file's own settings plus the new favorites, never this run's flag overrides.
            self.file_config = replace(self.file_config, favorites=self.config.favorites)
            save_config(self.file_config, self.config_path)
        except OSError as exc:
            return f" (could not save: {exc.strerror or exc})"
        return ""

    def _repaint_grid(self) -> None:
        if len(self.store):
            data_old = self.scheduler.freshness().data_old
            self.query_one(ScoreGrid).update_games(
                self.store.games, self.glyphs, self.store.rule, data_old=data_old, favorites=self.favorites
            )

    # --- switching -------------------------------------------------------------

    @property
    def week(self) -> int | None:
        """The week on screen: what was asked for, else what ESPN's latest board says."""
        if self.scheduler.week is not None:
            return self.scheduler.week
        board = self.scheduler.scoreboard
        return board.week if board is not None else None

    def _switch(self, *, week: int | None, group: int, what: str) -> None:
        self.scheduler.switch(week=week, group=group)
        self.query_one(ScoreGrid).clear()
        self.query_one(ScoreGrid).set_message(f"{self.glyphs.loading} Loading {what}")
        self.query_one(Ticker).clear_log()
        self._quiet_first_poll = True
        self._tick()

    def action_week(self, step: int) -> None:
        current = self.week
        if current is None:
            self.notify("Still loading; try again in a moment.", timeout=2)
            return
        if (step < 0 and current <= MIN_WEEK) or (step > 0 and current >= MAX_WEEK):
            edge = "first" if step < 0 else "last"
            self.notify(f"Week {current} is the {edge} week shown here.", timeout=2)
            return
        target = min(max(current + step, MIN_WEEK), MAX_WEEK)
        self._switch(week=target, group=self.scheduler.group, what=f"week {target}")

    def action_this_week(self) -> None:
        if self.scheduler.week is None:
            self.notify("Already on the current week.", timeout=2)
            return
        self._switch(week=None, group=self.scheduler.group, what="the current week")

    def action_toggle_group(self) -> None:
        other = GROUP_FCS if self.scheduler.group == GROUP_FBS else GROUP_FBS
        self._switch(week=self.scheduler.week, group=other, what=GROUP_NAMES[other])

    # --- actions ---------------------------------------------------------------

    def action_refresh(self) -> None:
        self.scheduler.refresh()

    def action_cycle_glyphs(self) -> None:
        self.glyphs = glyph_tables.get(glyph_tables.next_name(self.glyphs.name))
        self.query_one(Ticker).set_glyphs(self.glyphs)
        self._repaint_grid()
        self._tick()
        self.notify(f"Glyph set: {self.glyphs.name}", timeout=2)


def run() -> None:
    CfbApp().run()


if __name__ == "__main__":
    run()
