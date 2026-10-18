"""SettingsScreen: the few settings worth changing in the app, applied and saved as they change."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from cfbtui.config import LAYOUTS
from cfbtui.ui.glyphs import GLYPH_SET_NAMES


@dataclass(frozen=True, slots=True)
class Setting:
    key: str  # "alerts", "auto_update", "glyph_set" or "layout"
    label: str
    choices: tuple[str, ...]  # what Enter cycles through


SETTINGS = (
    Setting("alerts", "Alerts", ("on", "off")),
    Setting("auto_update", "Auto-update", ("on", "off")),
    Setting("glyph_set", "Icon style", GLYPH_SET_NAMES),
    Setting("layout", "Default layout", LAYOUTS),
)


def next_choice(setting: Setting, current: str) -> str:
    choices = setting.choices
    return choices[(choices.index(current) + 1) % len(choices)] if current in choices else choices[0]


class SettingsScreen(Screen[None]):
    """Enter changes the highlighted setting. ``on_change(key, value)`` applies and saves it
    and returns a note for the user (empty when all went well)."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
    ]

    DEFAULT_CSS = """
    SettingsScreen { layout: vertical; }
    SettingsScreen > Static { padding: 1 2 0 2; }
    SettingsScreen > OptionList { height: auto; margin: 1 2; border: round $panel-lighten-2; }
    """

    def __init__(self, values: dict[str, str], on_change: Callable[[str, str], str]) -> None:
        super().__init__()
        self.values = dict(values)
        self.on_change = on_change

    def compose(self) -> ComposeResult:
        yield Static("Enter changes the highlighted setting. Changes apply at once and are saved.")
        yield OptionList(*(Option(self._prompt(s), id=s.key) for s in SETTINGS))
        yield Footer()

    def _prompt(self, setting: Setting) -> str:
        return f"{setting.label:<16}{self.values[setting.key]}"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        options = self.query_one(OptionList)
        index = options.highlighted
        if index is None:
            return
        setting = SETTINGS[index]
        value = next_choice(setting, self.values[setting.key])
        self.values[setting.key] = value
        options.replace_option_prompt_at_index(index, self._prompt(setting))
        note = self.on_change(setting.key, value)
        self.notify(f"{setting.label}: {value}{note}", timeout=2)

    def action_close(self) -> None:
        self.dismiss()
