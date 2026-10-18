"""HelpScreen: every key, including the ones the footer has no room for."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from rich.table import Table
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


def help_rows(bindings: Iterable[Binding], display: Callable[[Binding], str]) -> list[tuple[str, str]]:
    """``(key, description)`` for each binding, in declaration order, plus the screens' own Esc."""
    rows = [(display(b), b.description) for b in bindings if b.description]
    rows.append(("Esc", "Back from a screen"))
    return rows


class HelpScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("question_mark", "close", "Close", show=False),
    ]

    DEFAULT_CSS = """
    HelpScreen { layout: vertical; }
    HelpScreen > VerticalScroll { height: 1fr; padding: 1 2; }
    """

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        table = Table(box=None, padding=(0, 2), show_header=False)
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        for key, description in self.rows:
            table.add_row(key, description)
        with VerticalScroll():
            yield Static(table, id="keys")
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()
