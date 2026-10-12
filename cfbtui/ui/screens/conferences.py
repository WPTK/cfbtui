"""ConferenceScreen: a small picker for the conference filter."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, OptionList
from textual.widgets.option_list import Option

ALL = ""  # the value dismissed for "All conferences"


class ConferenceScreen(ModalScreen[str | None]):
    """Dismisses with a conference id, ``ALL`` for every conference, or ``None`` when cancelled."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ConferenceScreen { align: center middle; }
    ConferenceScreen > Vertical {
        width: 40;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }
    ConferenceScreen OptionList { height: auto; max-height: 24; border: none; }
    """

    def __init__(self, conferences: list[tuple[str, str]], current: str | None) -> None:
        super().__init__()
        self.conferences = conferences
        self.current = current

    def compose(self) -> ComposeResult:
        options = [Option("All conferences", id="all")]
        options += [Option(name, id=f"c{cid}") for cid, name in self.conferences]
        with Vertical() as box:
            box.border_title = "Conference"
            yield OptionList(*options)
        yield Footer()

    def on_mount(self) -> None:
        picker = self.query_one(OptionList)
        ids = ["all", *(f"c{cid}" for cid, _ in self.conferences)]
        wanted = "all" if self.current is None else f"c{self.current}"
        picker.highlighted = ids.index(wanted) if wanted in ids else 0
        picker.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id or "all"
        self.dismiss(ALL if option_id == "all" else option_id.removeprefix("c"))

    def action_cancel(self) -> None:
        self.dismiss(None)
