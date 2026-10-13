"""The machine-wide input timer: a number on Windows, a shrug elsewhere, never an exception."""
from __future__ import annotations

import sys

from cfbtui import presence
from cfbtui.presence import seconds_since_input


def test_reports_a_non_negative_age_on_windows_and_none_elsewhere():
    age = seconds_since_input()
    if sys.platform == "win32":
        assert age is None or age >= 0.0  # None only in a session with no desktop
    else:
        assert age is None


def test_a_failing_system_call_is_an_unknown_not_a_crash(monkeypatch):
    def boom() -> float:
        raise OSError("no desktop here")

    monkeypatch.setattr(presence, "_windows_idle_seconds", boom)
    monkeypatch.setattr(sys, "platform", "win32")
    assert seconds_since_input() is None
