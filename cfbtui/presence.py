"""Is anyone at the computer?

The poll scheduler slows down when the user has walked away, not when the
terminal loses focus: the scoreboard may be on a second monitor while they
work in another window. So presence is machine-wide, measured as seconds since
the last keyboard or mouse input anywhere.

Windows answers through ``GetLastInputInfo``. Elsewhere, and whenever the call
fails, :func:`seconds_since_input` returns ``None`` and the scheduler assumes
someone is there, which is the fast and safe mistake.
"""
from __future__ import annotations

import ctypes
import sys


def seconds_since_input() -> float | None:
    """Seconds since the last keyboard or mouse input on this machine, or ``None`` if unknown."""
    if sys.platform != "win32":
        return None
    try:
        return _windows_idle_seconds()
    except Exception:  # a missing DLL, a sandbox, a session with no desktop
        return None


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = (("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint))


def _windows_idle_seconds() -> float | None:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    # Both are 32-bit millisecond tick counts; the subtraction wraps correctly in 32 bits.
    elapsed_ms = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0
