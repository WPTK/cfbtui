"""The Textual application: a score grid, a ticker and a status bar fed by a poll scheduler.

The scheduler runs in a worker and hands each :class:`~cfbtui.poll.PollResult`
back as a :class:`PollUpdated` message. Everything the user sees is repainted
from the store's current games, so a failed poll simply leaves the last good
cards on screen while the status bar says how old they are.

Keys: ``?`` lists every key (the footer shows only the core five), ``q`` quit,
``r`` refresh now, ``g`` cycle the glyph set, ``[`` and ``]`` previous and next
week, ``t`` this week, ``f`` toggle FBS and FCS, arrow keys move between cards,
``1`` and ``2`` star or unstar the focused card's away and home team, ``Enter``
opens the focused game's detail screen, ``R`` the AP and Coaches polls (``Esc``
returns from either), ``c`` copies the focused game as
Discord Markdown and ``C`` copies every visible game.

**Screens.** Detail and rankings are pushed over the grid. Polling keeps
running underneath, and while one is open the grid's own keys are switched off
(:meth:`CfbApp.check_action`), so a week cannot change under it.

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

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Footer

from cfbtui import share
from cfbtui.clipboard import ClipboardError, copy_text
from cfbtui.config import Config, favorite_ids, save_config
from cfbtui.espn.client import GROUP_FBS, GROUP_FCS, EspnClient
from cfbtui.espn.models import Game, Ranking
from cfbtui.espn.periods import MAX_WEEK, MIN_WEEK, week_label
from cfbtui.poll import PollIntervals, PollResult, PollScheduler, ScoreboardSource
from cfbtui.state.events import Scored
from cfbtui.state.store import GameStore
from cfbtui.ui import glyphs as glyph_tables
from cfbtui.ui.filters import FILTER_LABELS, conference_name, conferences_on, describe, keep, next_filter
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.pulse import PulseGate, pulse_kind
from cfbtui.ui.screens.conferences import ConferenceScreen
from cfbtui.ui.screens.detail import DetailScreen
from cfbtui.ui.screens.help import HelpScreen, help_rows
from cfbtui.ui.screens.rankings import RankingsScreen
from cfbtui.ui.widgets.score_grid import ScoreGrid
from cfbtui.ui.widgets.status_bar import StatusBar, StatusView
from cfbtui.ui.widgets.ticker import Ticker
from cfbtui.update import UpdateInfo, update_message

GROUP_NAMES = {GROUP_FBS: "FBS", GROUP_FCS: "FCS"}


class PollUpdated(Message):
    """A poll finished, good or bad. Carries the scheduler's result."""

    def __init__(self, result: PollResult) -> None:
        super().__init__()
        self.result = result


class CfbApp(App[None]):
    TITLE = "cfbtui"
    CSS_PATH = "ui/app.tcss"
    # Only the first five show in the footer, so it fits 60 columns; `?` lists the rest.
    BINDINGS = [
        ("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("enter", "detail", "Detail"),
        Binding("l", "cycle_filter", "Filter"),
        Binding("R", "rankings", "Rankings"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("g", "cycle_glyphs", "Glyphs", show=False),
        Binding("left_square_bracket", "week(-1)", "Prev week", show=False),
        Binding("right_square_bracket", "week(1)", "Next week", show=False),
        Binding("t", "this_week", "This week", show=False),
        Binding("f", "toggle_group", "FBS/FCS", show=False),
        Binding("1", "favorite('away')", "Star away", show=False),
        Binding("2", "favorite('home')", "Star home", show=False),
        Binding("c", "copy_game", "Copy game", show=False),
        Binding("C", "copy_board", "Copy all", show=False),
        Binding("v", "toggle_layout", "Grid/list", show=False),
        Binding("o", "conference", "Conference", show=False),
    ]

    # Actions that belong to the grid; they are off while a detail or rankings screen is on top.
    GRID_ACTIONS = frozenset(
        {"help", "refresh", "week", "this_week", "toggle_group", "favorite", "detail", "rankings", "copy_game",
         "copy_board", "toggle_layout", "cycle_filter", "conference"}
    )

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
        update_check: Callable[[], Awaitable[UpdateInfo | None]] | None = None,
        detail_refresh: float | None = None,
    ) -> None:
        """Explicit arguments win over ``config``, which wins over the built-in defaults.

        ``config_path`` is where favorites are saved; ``None`` means nowhere.
        ``update_check`` is an async callable that finds a newer release (or ``None``).
        ``detail_refresh`` is the seconds between the detail screen's fetches; ``None`` keeps its own.
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
        self.alerts_enabled = True  # gates card pulses; to be wired to config.alerts.enabled
        self._pulses = PulseGate()
        self.detail_refresh = detail_refresh
        self.copier: Callable[[str], None] = copy_text
        self._copy_parts: list[str] = []
        self._copy_next = 0
        self.update_check = update_check
        self.layout = view.layout
        self.filter = "all"
        self.conference: str | None = None
        self.cfp: Ranking | None = None  # the last CFP ranking seen; once released it replaces AP and Coaches

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        return not (action in self.GRID_ACTIONS and len(self.screen_stack) > 1)

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
        if self.update_check is not None:
            self.run_worker(self._look_for_update(), name="update", group="update", exit_on_error=False)
        self.set_interval(1.0, self._tick)
        self._tick()

    async def on_unmount(self) -> None:
        self.scheduler.stop()
        if self._owns_client and isinstance(self.client, EspnClient):
            await self.client.aclose()

    # --- poll results ----------------------------------------------------------

    def on_poll_updated(self, message: PollUpdated) -> None:
        # the screen may be torn down while a last poll lands
        with contextlib.suppress(NoMatches):
            self._show_result(message.result)

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
            self._paint_grid(data_old=False)
            if not quiet:
                self.query_one(Ticker).add_events(result.events, stamp=datetime.now())
                for event in result.events:
                    if isinstance(event, Scored):
                        grid.flash(event.game_id, event.team.id)
                    elif self.alerts_enabled and (kind := pulse_kind(event)) and self._pulses.allow(
                        event.game_id, kind
                    ):
                        grid.pulse(event.game_id, kind)
            self._feed_detail()
        elif self.scheduler.scoreboard is None:
            grid.set_message(f"{self.glyphs.error} Could not reach ESPN. Retrying. ({result.error})")
        self._tick()

    def _tick(self) -> None:
        self.scheduler.observe_presence()
        # the screen may be torn down
        with contextlib.suppress(NoMatches):
            self._update_status()

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
            away=self.scheduler.away,
            glyph_set=self.glyphs.name,
            errors=len(self.store.last_errors),
            view_note=describe(self.filter, self.conference, self.layout),
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

    def _visible(self) -> list[Game]:
        return [g for g in self.store.games if keep(g, self.filter, self.favorites, self.conference, self.store.rule)]

    def _paint_grid(self, *, data_old: bool) -> None:
        plain = self.filter == "all" and self.conference is None
        self.query_one(ScoreGrid).update_games(
            self._visible(),
            self.glyphs,
            self.store.rule,
            data_old=data_old,
            favorites=self.favorites,
            compact=self.layout == "list",
            empty_text="No games on the board." if plain else "No games match this view.",
        )

    def _repaint_grid(self) -> None:
        if len(self.store):
            self._paint_grid(data_old=self.scheduler.freshness().data_old)

    # --- switching -------------------------------------------------------------

    @property
    def week(self) -> int | None:
        """The week on screen: what was asked for, else what ESPN's latest board says."""
        if self.scheduler.week is not None:
            return self.scheduler.week
        board = self.scheduler.scoreboard
        return board.week if board is not None else None

    def _switch(self, *, week: int | None, group: int, what: str) -> None:
        while len(self.screen_stack) > 1:  # a screen showing the old week or group has nothing left to show
            self.pop_screen()
        self.scheduler.switch(week=week, group=group)
        self.query_one(ScoreGrid).clear()
        self.query_one(ScoreGrid).set_message(f"{self.glyphs.loading} Loading {what}")
        self.query_one(Ticker).clear_log()
        self._quiet_first_poll = True
        self._copy_parts, self._copy_next = [], 0
        self._tick()

    def action_week(self, step: int) -> None:
        current = self.week
        if current is None:
            self.notify("Still loading; try again in a moment.", timeout=2)
            return
        if (step < 0 and current <= MIN_WEEK) or (step > 0 and current >= MAX_WEEK):
            edge = "first" if step < 0 else "last"
            self.notify(f"{week_label(current)} is the {edge} week shown here.", timeout=2)
            return
        target = min(max(current + step, MIN_WEEK), MAX_WEEK)
        self._switch(week=target, group=self.scheduler.group, what=week_label(target).lower())

    def action_this_week(self) -> None:
        if self.scheduler.week is None:
            self.notify("Already on the current week.", timeout=2)
            return
        self._switch(week=None, group=self.scheduler.group, what="the current week")

    def action_toggle_group(self) -> None:
        other = GROUP_FCS if self.scheduler.group == GROUP_FBS else GROUP_FBS
        self.conference = None  # a conference from one board means nothing on the other
        self._switch(week=self.scheduler.week, group=other, what=GROUP_NAMES[other])

    # --- screens ---------------------------------------------------------------

    def action_help(self) -> None:
        bindings = Binding.make_bindings(self.BINDINGS)
        self.push_screen(HelpScreen(help_rows(bindings, lambda b: b.key_display or self.get_key_display(b))))

    def action_detail(self) -> None:
        card = self.query_one(ScoreGrid).focused_card
        if card is None:
            self.notify("Focus a card with the arrow keys first.", timeout=3)
            return
        game = self.store.get(card.game.id) or card.game
        refresh = self.detail_refresh
        extra = {} if refresh is None else {"live_refresh": refresh, "idle_refresh": refresh}
        self.push_screen(DetailScreen(self.client, game, self.glyphs, **extra))

    def action_rankings(self) -> None:
        self.push_screen(
            RankingsScreen(
                self.client,
                self.glyphs,
                group=self.scheduler.group,
                remembered_cfp=self.cfp,
                on_cfp=self._remember_cfp,
            )
        )

    def _remember_cfp(self, poll: Ranking) -> None:
        self.cfp = poll

    def _feed_detail(self) -> None:
        screen = self.screen
        if isinstance(screen, DetailScreen):
            game = self.store.get(screen.game.id)
            if game is not None:
                screen.update_game(game)

    # --- view ------------------------------------------------------------------

    def _view_changed(self, note: str) -> None:
        self._copy_parts, self._copy_next = [], 0
        self._repaint_grid()
        self._tick()
        self.notify(note, timeout=2)

    def action_toggle_layout(self) -> None:
        self.layout = "grid" if self.layout == "list" else "list"
        self._view_changed(f"Layout: {self.layout}")

    def action_cycle_filter(self) -> None:
        self.filter = next_filter(self.filter)
        self._view_changed(f"Showing: {FILTER_LABELS[self.filter]}")

    def action_conference(self) -> None:
        options = conferences_on(self.store.games)
        if not options:
            self.notify("No conferences to pick from yet.", timeout=3)
            return
        self.push_screen(ConferenceScreen(options, self.conference), self._conference_picked)

    def _conference_picked(self, chosen: str | None) -> None:
        if chosen is None:
            return
        self.conference = chosen or None
        name = conference_name(chosen) if chosen else "all conferences"
        self._view_changed(f"Showing: {name}")

    async def _look_for_update(self) -> None:
        if self.update_check is None:
            return
        info = await self.update_check()
        if info is not None:
            self.notify(update_message(info), title="Update available", timeout=20)

    # --- copy ------------------------------------------------------------------

    def action_copy_game(self) -> None:
        card = self.query_one(ScoreGrid).focused_card
        if card is None:
            self.notify("Focus a card with the arrow keys first.", timeout=3)
            return
        game = self.store.get(card.game.id) or card.game
        self._copy(share.format_game(game, share.UNICODE), "game")

    def action_copy_board(self) -> None:
        games = [card.game for card in self.query_one(ScoreGrid).cards]
        board = self.scheduler.scoreboard
        week = board.week if board and board.week is not None else self.scheduler.week
        title = f"{week_label(week)} {GROUP_NAMES.get(self.scheduler.group, '')}".strip() if week else None
        parts = share.format_board(games, share.UNICODE, title=title)
        if not parts:
            self.notify("No games to copy yet.", timeout=3)
            return
        # One clipboard holds one message. A long board is copied a part at a time:
        # pressing C again moves to the next part. Scores and clocks change between
        # presses, so only a change in the number of parts (or a switch) starts over.
        if len(parts) != len(self._copy_parts):
            self._copy_next = 0
        self._copy_parts = parts
        index = self._copy_next
        label = "board" if len(parts) == 1 else f"board, part {index + 1} of {len(parts)}"
        if self._copy(parts[index], label):
            self._copy_next = (index + 1) % len(parts)
            if len(parts) > 1:
                last = index == len(parts) - 1
                more = "That was the last part; C starts over." if last else "Press C again for the next part."
                self.notify(more, timeout=3)

    def _copy(self, text: str, what: str) -> bool:
        try:
            self.copier(text)
        except ClipboardError as exc:
            self.notify(f"Could not copy: {exc}. Is a clipboard tool installed?", severity="error", timeout=6)
            return False
        self.notify(f"Copied {what} for Discord", timeout=2)
        return True

    # --- actions ---------------------------------------------------------------

    def action_refresh(self) -> None:
        self.scheduler.refresh()

    def action_cycle_glyphs(self) -> None:
        self.glyphs = glyph_tables.get(glyph_tables.next_name(self.glyphs.name))
        for screen in self.screen_stack:
            if isinstance(screen, DetailScreen):
                screen.set_glyphs(self.glyphs)
        self.query_one(Ticker).set_glyphs(self.glyphs)
        self._repaint_grid()
        self._tick()
        self.notify(f"Glyph set: {self.glyphs.name}", timeout=2)


def run() -> None:
    CfbApp().run()


if __name__ == "__main__":
    run()
