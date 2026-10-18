"""Which store events pulse a card, and how often.

A pulse is the slow border "breathe" a card shows when its game enters the Red Zone,
Upset Watch or Overtime, or goes Final (see ``GameCard.pulse``). It fires on the
transition the store reports, never on state, and each (game, kind) pair has a short
cool-down so a game bouncing in and out of the red zone does not pulse every poll.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from cfbtui.state.events import Event, GameFinal, PeriodChanged, RedZone, UpsetWatch

COOLDOWN_SECONDS = 120.0


def pulse_kind(event: Event) -> str | None:
    """The pulse kind for ``event``, or ``None`` when the event does not pulse."""
    if isinstance(event, RedZone):
        return "redzone"
    if isinstance(event, UpsetWatch):
        return "upset"
    if isinstance(event, PeriodChanged) and event.is_overtime:
        return "overtime"
    if isinstance(event, GameFinal):
        return "final"
    return None


class PulseGate:
    """Lets a (game, kind) pulse through at most once per ``cooldown`` seconds."""

    def __init__(self, cooldown: float = COOLDOWN_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self.cooldown = cooldown
        self._clock = clock
        self._last: dict[tuple[str, str], float] = {}

    def allow(self, game_id: str, kind: str) -> bool:
        now = self._clock()
        last = self._last.get((game_id, kind))
        if last is not None and now - last < self.cooldown:
            return False
        self._last[game_id, kind] = now
        return True
