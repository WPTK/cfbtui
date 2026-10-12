"""The Textual application.

Phase 0: a hello-world screen that proves truecolor rendering in Windows
Terminal by painting a row of real team colors. The scoreboard arrives in Phase 2.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Static

from cfbtui.ui.theme import foreground_for, hex_color
from cfbtui.ui.widgets.status_bar import StatusBar

# (abbreviation, ESPN primary color, ESPN alternate color)
SWATCHES: list[tuple[str, str, str]] = [
    ("LSU", "461d7c", "fdd023"),
    ("SC", "73000a", "000000"),
    ("TEX", "bf5700", "ffffff"),
    ("OU", "841617", "fdf9d8"),
    ("UGA", "ba0c2f", "000000"),
    ("MICH", "00274c", "ffcb05"),
]


class Swatch(Static):
    """A block painted in a team's primary color with a readable label."""

    def __init__(self, abbreviation: str, primary: str, alternate: str) -> None:
        super().__init__(abbreviation)
        self._primary = hex_color(primary)
        self._alternate = hex_color(alternate)

    def on_mount(self) -> None:
        self.styles.background = self._primary
        self.styles.color = foreground_for(self._primary)
        self.styles.border = ("heavy", self._alternate)


class CfbApp(App[None]):
    TITLE = "cfbtui"
    CSS_PATH = "ui/app.tcss"
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Static("cfbtui  ·  college football scoreboard", id="banner")
        with Horizontal(id="swatches"):
            for abbreviation, primary, alternate in SWATCHES:
                yield Swatch(abbreviation, primary, alternate)
        yield Static(
            "Phase 0 truecolor check. Six distinct team colors with contrasting borders "
            "means Windows Terminal is rendering 24-bit color.",
            id="hint",
        )
        yield Static(id="spacer")
        yield StatusBar()
        yield Footer()


def run() -> None:
    CfbApp().run()


if __name__ == "__main__":
    run()
