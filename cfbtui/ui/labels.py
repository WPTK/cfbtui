"""Small text helpers shared by the card, the detail screen, the ticker, the status line and Discord copy."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cfbtui.espn.models import Game
from cfbtui.ui.glyphs import Glyphs

EASTERN = ZoneInfo("America/New_York")
# A kickoff further out than this shows its date, so next week's game never looks like this week's.
FAR_KICKOFF = timedelta(days=5)


def period_name(period: int) -> str:
    """``Q1``..``Q4``, ``OT`` for the fifth period, ``OT2`` and up after that."""
    if period > 5:
        return f"OT{period - 4}"
    if period > 4:
        return "OT"
    return f"Q{period}"


def pretty_status(name: str) -> str:
    """``STATUS_RAIN_DELAY`` as ``Rain Delay``."""
    return name.removeprefix("STATUS_").replace("_", " ").title()


def kickoff_text(when: datetime, now: datetime | None = None) -> str:
    """``"Sat 12:00 PM ET"``, or ``"Sat Oct 24 12:00 PM ET"`` when the kickoff is over five days away.

    Eastern time, no leading zero on the hour or the day.
    """
    local = when.astimezone(EASTERN)
    far = now is not None and when - now > FAR_KICKOFF
    text = local.strftime("%a %b %d %I:%M %p" if far else "%a %I:%M %p")
    return re.sub(r" 0(\d)", r" \1", text) + " ET"


def status_text(game: Game, glyphs: Glyphs, now: datetime | None = None) -> str:
    s = game.status
    if game.is_pregame:
        if s.name == "STATUS_SCHEDULED":
            return f"{glyphs.pregame} {kickoff_text(game.date, now)}"
        return f"{glyphs.pregame} {s.short_detail or pretty_status(s.name)}"
    if game.is_live:
        if s.is_halftime:
            return f"{glyphs.halftime} Halftime"
        if s.name == "STATUS_END_PERIOD":
            return f"{glyphs.live} {s.short_detail or f'End of Q{s.period}'}"
        if s.name not in _PLAYING:
            return f"{glyphs.live} {s.short_detail or pretty_status(s.name)}"
        return f"{glyphs.live} {period_name(s.period)} {s.clock}"
    if game.is_final:
        return f"{glyphs.final} Final{'/OT' if s.is_overtime else ''}"
    return f"{glyphs.final} {s.short_detail or pretty_status(s.name)}"


_PLAYING = frozenset(
    {
        "STATUS_IN_PROGRESS",
        "STATUS_FIRST_HALF",
        "STATUS_SECOND_HALF",
        "STATUS_OVERTIME",
    }
)
