"""System clipboard access, behind one function so the app and its tests can swap it out."""
from __future__ import annotations

import pyperclip


class ClipboardError(Exception):
    """No clipboard mechanism is available, or it refused the text."""


def copy_text(text: str) -> None:
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        raise ClipboardError(str(exc).strip().splitlines()[0] if str(exc).strip() else "no clipboard available") from exc
