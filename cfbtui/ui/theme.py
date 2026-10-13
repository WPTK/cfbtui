"""Color helpers: ESPN team hex colors to Textual-friendly values."""
from __future__ import annotations

from rich.style import Style
from textual.color import Color

WHITE = "#ffffff"
BLACK = "#000000"
FALLBACK = "#444444"


def hex_color(value: str | None, fallback: str = FALLBACK) -> str:
    """Normalise an ESPN color field (``"461d7c"``) to ``"#461d7c"``.

    ESPN omits the leading ``#`` and sometimes the field entirely.
    """
    if not value:
        return fallback
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        return fallback
    try:
        int(v, 16)
    except ValueError:
        return fallback
    return f"#{v.lower()}"


def team_style(background: str | None, **attrs: bool) -> Style:
    """The one team look used everywhere: readable text on the team's color."""
    bg = hex_color(background)
    return Style(color=foreground_for(bg), bgcolor=bg, **attrs)


def foreground_for(background: str) -> str:
    """Black or white, whichever reads better on ``background``.

    Uses WCAG relative luminance with the usual 0.5 split, which handles
    team palettes well: LSU purple gets white, Michigan maize gets black.
    """
    color = Color.parse(hex_color(background))
    return BLACK if color.brightness > 0.5 else WHITE
