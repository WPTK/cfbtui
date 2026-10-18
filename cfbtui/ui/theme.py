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


# Terminal background assumed behind bars and sparklines (Textual's dark theme); card grids and headers paint
# their own background, so they do not need this.
TERMINAL_BG = "#121212"
MIN_CONTRAST = 3.0  # WCAG's floor for large or graphical elements
MIN_DISTANCE = 80.0  # RGB distance below which two team colours look alike


def _rgb(value: str) -> tuple[int, int, int]:
    c = Color.parse(hex_color(value))
    return c.r, c.g, c.b


def luminance(value: str) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""

    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _toward(value: str, target: str, amount: float) -> str:
    r, g, b = (round(s + (t - s) * amount) for s, t in zip(_rgb(value), _rgb(target), strict=True))
    return f"#{r:02x}{g:02x}{b:02x}"


def readable_on(color: str | None, alt: str | None = None, background: str = TERMINAL_BG) -> str:
    """``color`` if it shows on ``background``, else ``alt`` if that does, else ``color`` lightened or darkened."""
    primary = hex_color(color)
    for candidate in (primary, hex_color(alt, "")):
        if candidate and contrast(candidate, background) >= MIN_CONTRAST:
            return candidate
    target = WHITE if luminance(background) < 0.5 else BLACK
    for step in range(1, 11):
        shifted = _toward(primary, target, step / 10)
        if contrast(shifted, background) >= MIN_CONTRAST:
            return shifted
    return target


def distance(a: str, b: str) -> float:
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b), strict=True)) ** 0.5


def bar_colors(
    away: tuple[str | None, str | None], home: tuple[str | None, str | None], background: str = TERMINAL_BG
) -> tuple[str, str]:
    """Readable bar colours for two ``(color, alt)`` pairs, kept apart: if they look alike the home side
    switches to its alt colour, and failing that is pushed away from the away side's colour."""
    a = readable_on(*away, background)
    h = readable_on(*home, background)
    if distance(a, h) >= MIN_DISTANCE:
        return a, h
    alt = readable_on(home[1], None, background)
    if distance(a, alt) >= MIN_DISTANCE:
        return a, alt
    target = WHITE if luminance(a) < 0.5 else BLACK
    for step in range(1, 11):
        shifted = readable_on(_toward(h, target, step / 10), None, background)
        if distance(a, shifted) >= MIN_DISTANCE:
            return a, shifted
    return a, h
