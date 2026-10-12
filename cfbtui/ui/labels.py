"""Small text helpers shared by the card, the ticker and the status line."""
from __future__ import annotations


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
