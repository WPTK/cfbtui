"""ScoreGrid: the game cards in a grid that reflows with the terminal width.

Order: live games first, then pregame by kickoff, then everything else
(finals, postponements) by kickoff. Within a group the order is kickoff time
then game id, which never changes during a game, so cards do not jump around
between polls. A game only moves when its state moves it to another group.
"""
from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Static

from cfbtui.espn.models import Game
from cfbtui.state.upset import UpsetRule
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.widgets.game_card import GameCard

CARD_MIN_WIDTH = 36


def sort_key(game: Game) -> tuple[int, float, str]:
    group = 0 if game.is_live else 1 if game.is_pregame else 2
    return (group, game.date.timestamp(), game.id)


def columns_for(width: int) -> int:
    return max(1, width // CARD_MIN_WIDTH)


class ScoreGrid(VerticalScroll):
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
    ScoreGrid > #message {
        height: auto;
        padding: 1 2;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cards: dict[str, GameCard] = {}

    def compose(self) -> ComposeResult:
        yield Static("", id="message")
        yield Grid(id="cards")

    @property
    def cards(self) -> list[GameCard]:
        """Cards in display order."""
        return [c for c in self.query_one("#cards", Grid).children if isinstance(c, GameCard)]

    def card_for(self, game_id: str) -> GameCard | None:
        return self._cards.get(game_id)

    def set_message(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def on_resize(self) -> None:
        self._set_columns()

    def _set_columns(self) -> None:
        try:
            grid = self.query_one("#cards", Grid)
        except NoMatches:  # a resize can arrive before compose has mounted the grid
            return
        grid.styles.grid_size_columns = columns_for(self.size.width - 2)

    def update_games(
        self,
        games: Iterable[Game],
        glyphs: Glyphs,
        rule: UpsetRule,
        *,
        data_old: bool = False,
    ) -> None:
        """Make the grid show exactly ``games``: add, update, remove and reorder cards."""
        ordered = sorted(games, key=sort_key)
        grid = self.query_one("#cards", Grid)
        wanted = {g.id for g in ordered}
        for game_id in [gid for gid in self._cards if gid not in wanted]:
            self._cards.pop(game_id).remove()
        for game in ordered:
            verdict = rule.evaluate(game)
            card = self._cards.get(game.id)
            if card is None:
                card = GameCard(game, glyphs, verdict=verdict)
                card.set_data_old(data_old)
                self._cards[game.id] = card
                grid.mount(card)
            else:
                card.show(game, glyphs, verdict, data_old=data_old)
        self.call_after_refresh(self._reorder, [g.id for g in ordered])
        self.set_message("" if ordered else "No games on the board.")
        self._set_columns()

    def _reorder(self, order: list[str]) -> None:
        grid = self.query_one("#cards", Grid)
        if [c.game_id for c in grid.children if isinstance(c, GameCard)] == [i for i in order if i in self._cards]:
            return
        for index, game_id in enumerate(order):
            card = self._cards.get(game_id)
            if card is None or not card.is_attached:
                continue
            children = list(grid.children)
            if index < len(children) and children[index] is not card:
                grid.move_child(card, before=index)

    def flash(self, game_id: str, team_id: str) -> None:
        card = self._cards.get(game_id)
        if card is not None:
            card.flash(team_id)

    def set_data_old(self, data_old: bool) -> None:
        for card in self._cards.values():
            card.set_data_old(data_old)
