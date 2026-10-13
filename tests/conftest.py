"""Shared fixtures."""
from __future__ import annotations

import pytest

from cfbtui import presence


@pytest.fixture(autouse=True)
def someone_is_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the real keyboard-and-mouse idle timer.

    Otherwise anything that builds a scheduler without its own ``idle_for`` would pass while
    the developer is typing and fail once they have been away from the machine for five minutes.
    """
    monkeypatch.setattr(presence, "seconds_since_input", lambda: 0.0)
