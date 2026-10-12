"""Bottom status line: version, local clock, and (later) poll state."""
from __future__ import annotations

from datetime import datetime

from textual.widgets import Static

from cfbtui import __version__


class StatusBar(Static):
    """One-line status strip. Phase 0 shows the version and a ticking local clock."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text-muted;
    }
    """

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        now = datetime.now().astimezone()
        # %Z expands to "Eastern Daylight Time" on Windows; keep the line short.
        self.update(f"cfbtui v{__version__}  ·  {now:%a %b %d %H:%M:%S}  ·  q quits")
