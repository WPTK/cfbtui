"""ScoreGrid: the game cards in a grid that reflows with the terminal width.

Order: live games first, then pregame by kickoff, then everything else
(finals, postponements) by kickoff. Within a group the order is kickoff time
then game id, which never changes during a game, so cards do not jump around
between polls. A game only moves when its state moves it to another group.

Games involving a favorite team come first of all, ordered the same way among
themselves, under a "Favorites" heading, with the rest under "Other games".
With no favorites on the board there are no headings.

The ``compact`` layout is one line per game in a single column; the same cards,
the same focus movement, a different height.

Arrow keys move focus between cards in display order (left and right by one,
up and down by a row), so a key binding can act on "the focused game".
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from cfbtui.espn.models import Game
from cfbtui.state.upset import UpsetRule
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.widgets.game_card import GameCard

CARD_MIN_WIDTH = 36


def is_starred(game: Game, favorites: frozenset[str]) -> bool:
    return game.away.id in favorites or game.home.id in favorites


def sort_key(game: Game, favorites: frozenset[str] = frozenset()) -> tuple[int, int, float, str]:
    starred = is_starred(game, favorites)
    group = 0 if game.is_live else 1 if game.is_pregame else 2
    return (0 if starred else 1, group, game.date.timestamp(), game.id)


def columns_for(width: int) -> int:
    return max(1, width // CARD_MIN_WIDTH)


def next_index(index: int, count: int, columns: int, key: str) -> int:
    """Where focus goes from ``index`` on a grid of ``count`` cards in ``columns`` columns.

    Movement clamps at the edges. Down from a short last row lands on the final card.
    """
    if count <= 0:
        return 0
    columns = max(1, columns)
    index = min(max(index, 0), count - 1)
    match key:
        case "left":
            return max(index - 1, 0)
        case "right":
            return min(index + 1, count - 1)
        case "up":
            return index - columns if index - columns >= 0 else index
        case "down":
            if index + columns < count:
                return index + columns
            return count - 1 if index // columns < (count - 1) // columns else index
    return index


class ScoreGrid(VerticalScroll):
    BINDINGS = [
        Binding("left", "move_focus('left')", show=False),
        Binding("right", "move_focus('right')", show=False),
        Binding("up", "move_focus('up')", show=False),
        Binding("down", "move_focus('down')", show=False),
    ]

    DEFAULT_CSS = """
    ScoreGrid {
        height: 1fr;
        padding: 0 1;
    }
    ScoreGrid > Grid {
        height: auto;
        grid-size: 1;
        grid-gutter: 0 1;
    }
    ScoreGrid > Grid > .section {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
    }
    ScoreGrid > #message {
        height: auto;
        padding: 1 2;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cards: dict[str, GameCard] = {}
        self._headers: dict[str, Static] = {}
        self._fillers: list[Static] = []
        self.columns = 1
        self.compact = False

    def compose(self) -> ComposeResult:
        yield Static("", id="message")
        yield Grid(id="cards")

    @property
    def cards(self) -> list[GameCard]:
        """Cards in display order."""
        live = set(self._cards.values())  # cards removed by clear() may linger in children for a moment
        return [c for c in self.query_one("#cards", Grid).children if c in live]

    def card_for(self, game_id: str) -> GameCard | None:
        return self._cards.get(game_id)

    @property
    def focused_card(self) -> GameCard | None:
        focused = self.app.focused
        return focused if isinstance(focused, GameCard) and focused in self._cards.values() else None

    def action_move_focus(self, key: str) -> None:
        cards = self.cards
        if not cards:
            return
        current = self.focused_card
        if current is None:
            cards[0].focus()
            return
        target = cards[next_index(cards.index(current), len(cards), self.columns, key)]
        target.focus()
        target.scroll_visible()

    def clear(self) -> None:
        """Drop every card, for a week or group switch."""
        for card in self._cards.values():
            card.remove()
        self._cards.clear()
        for header in self._headers.values():
            header.remove()
        self._headers.clear()
        self._drop_fillers()

    def set_message(self, text: str) -> None:
        # a poll can land before compose has finished or after teardown began
        with contextlib.suppress(NoMatches):
            message = self.query_one("#message", Static)
            message.update(Text(text))
            message.display = bool(text)

    def on_resize(self) -> None:
        self._set_columns()

    def _set_columns(self) -> None:
        try:
            grid = self.query_one("#cards", Grid)
        except NoMatches:  # a resize can arrive before compose has mounted the grid
            return
        self.columns = 1 if self.compact else columns_for(self.size.width - 2)
        grid.styles.grid_size_columns = self.columns
        for header in self._headers.values():
            header.styles.column_span = self.columns

    def update_games(
        self,
        games: Iterable[Game],
        glyphs: Glyphs,
        rule: UpsetRule,
        *,
        data_old: bool = False,
        favorites: frozenset[str] = frozenset(),
        compact: bool = False,
        empty_text: str = "No games on the board.",
    ) -> None:
        """Make the grid show exactly ``games``: add, update, remove and reorder cards."""
        self.compact = compact
        ordered = sorted(games, key=lambda g: sort_key(g, favorites))
        try:
            grid = self.query_one("#cards", Grid)
        except NoMatches:
            return
        wanted = {g.id for g in ordered}
        for game_id in [gid for gid in self._cards if gid not in wanted]:
            self._cards.pop(game_id).remove()
        for game in ordered:
            verdict = rule.evaluate(game)
            card = self._cards.get(game.id)
            if card is None:
                card = GameCard(game, glyphs, verdict=verdict, favorites=favorites, compact=compact)
                card.set_data_old(data_old)
                self._cards[game.id] = card
                grid.mount(card)
            else:
                card.show(game, glyphs, verdict, data_old=data_old, favorites=favorites, compact=compact)
        self._set_columns()
        starred = [g.id for g in ordered if is_starred(g, favorites)]
        rest = [g.id for g in ordered if not is_starred(g, favorites)]
        layout: list[Widget] = []
        if starred:
            layout.append(self._header(grid, "favorites", f"{glyphs.favorite} Favorites"))
            layout += [self._cards[i] for i in starred]
            if rest:
                layout += self._pad_row(grid, len(starred))
                layout.append(self._header(grid, "rest", "Other games"))
        for key in [k for k in self._headers if k not in {"favorites", "rest"} or not starred]:
            self._headers.pop(key).remove()
        if "rest" in self._headers and not rest:
            self._headers.pop("rest").remove()
        if not (starred and rest):
            self._drop_fillers()
        layout += [self._cards[i] for i in rest]
        self.call_after_refresh(self._reorder, layout)
        self.set_message("" if ordered else empty_text)
        self._set_columns()

    def _drop_fillers(self) -> None:
        for filler in self._fillers:
            filler.remove()
        self._fillers.clear()

    def _pad_row(self, grid: Grid, count: int) -> list[Static]:
        """Blank cells that finish the Favorites block's last row, so the next heading starts a fresh one."""
        need = (-count) % self.columns
        if len(self._fillers) != need:
            self._drop_fillers()
            self._fillers = [Static("", classes="filler") for _ in range(need)]
            for filler in self._fillers:
                grid.mount(filler)
        return list(self._fillers)

    def _header(self, grid: Grid, key: str, text: str) -> Static:
        header = self._headers.get(key)
        if header is None:
            header = self._headers[key] = Static(text, classes="section")
            grid.mount(header)
        else:
            header.update(text)
        return header

    def _reorder(self, layout: list[Widget]) -> None:
        grid = self.query_one("#cards", Grid)
        wanted = [w for w in layout if w.is_attached]
        for index, widget in enumerate(wanted):
            current = list(grid.children)
            if index < len(current) and current[index] is not widget:
                grid.move_child(widget, before=current[index])

    def flash(self, game_id: str, team_id: str) -> None:
        card = self._cards.get(game_id)
        if card is not None:
            card.flash(team_id)

    def set_data_old(self, data_old: bool) -> None:
        for card in self._cards.values():
            card.set_data_old(data_old)
