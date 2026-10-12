"""RankingsScreen: the AP and Coaches polls side by side, fetched once on open."""
from __future__ import annotations

from typing import Protocol

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from cfbtui.espn.client import EspnError
from cfbtui.espn.client import GROUP_FBS, GROUP_FCS
from cfbtui.espn.models import Ranking
from cfbtui.ui.glyphs import Glyphs


class RankingsSource(Protocol):
    async def rankings(self) -> tuple[Ranking, ...]: ...


def pick_polls(polls: tuple[Ranking, ...], group: int = GROUP_FBS) -> list[Ranking]:
    """The FBS AP and Coaches polls, in that order, or the FCS Coaches poll for the FCS board."""
    if group == GROUP_FCS:
        return [p for p in polls if p.type.lower() == "fcs"][:1]
    ap = next((p for p in polls if p.type.lower() == "ap"), None)
    coaches = next((p for p in polls if p.type.lower() == "usa"), None)
    if coaches is None:
        coaches = next(
            (p for p in polls if "coaches" in p.name.lower() and not any(w in p.name for w in ("FCS", "Div"))),
            None,
        )
    return [p for p in (ap, coaches) if p is not None]


def poll_title(poll: Ranking) -> str:
    week = f"  Week {poll.week}" if poll.week else ""
    when = f"  {poll.date:%b} {poll.date.day}" if poll.date else ""
    return f"{poll.name}{week}{when}"


def trend_text(previous: int | None, trend: str | None) -> str:
    if trend and trend not in {"-", "0"}:
        return trend
    return "new" if previous is None else ""


def poll_table(poll: Ranking) -> Table:
    table = Table(box=None, padding=(0, 1), show_header=True, header_style="bold", expand=False)
    table.add_column("#", justify="right")
    table.add_column("Team", no_wrap=True)
    table.add_column("Rec", no_wrap=True)
    table.add_column("Pts", justify="right")
    table.add_column("Chg", justify="right")
    for entry in poll.ranks:
        votes = f" ({entry.first_place_votes})" if entry.first_place_votes else ""
        points = f"{entry.points:.0f}" if entry.points is not None else ""
        table.add_row(
            str(entry.rank) if entry.rank is not None else "",
            Text(f"{entry.abbreviation:<5}{entry.name}{votes}", style=entry.color or ""),
            entry.record or "",
            points,
            trend_text(entry.previous, entry.trend),
        )
    return table


class RankingsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
    ]

    DEFAULT_CSS = """
    RankingsScreen { layout: vertical; }
    RankingsScreen > VerticalScroll { height: 1fr; padding: 1 2; }
    RankingsScreen Horizontal { height: auto; }
    RankingsScreen .poll { width: 1fr; height: auto; padding: 0 1; border: round $panel-lighten-2; }
    """

    def __init__(self, client: RankingsSource, glyphs: Glyphs, group: int = GROUP_FBS) -> None:
        super().__init__()
        self.group = group
        self.client = client
        self.glyphs = glyphs
        self.polls: list[Ranking] = []
        self.error: str | None = None
        self.loaded = False

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(f"{self.glyphs.loading} Loading the polls", id="status")
            yield Horizontal(id="polls")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load(), name="rankings", group="rankings", exclusive=True)

    async def _load(self) -> None:
        try:
            polls = await self.client.rankings()
        except EspnError as exc:
            self.error = str(exc) or type(exc).__name__
        except Exception as exc:  # a malformed payload must not kill the screen
            self.error = f"{type(exc).__name__}: {exc}"
        else:
            self.polls = pick_polls(polls, self.group)
        await self._paint()
        self.loaded = True

    async def _paint(self) -> None:
        status = self.query_one("#status", Static)
        holder = self.query_one("#polls", Horizontal)
        await holder.remove_children()
        if self.error:
            status.update(f"{self.glyphs.error} Could not load the polls ({self.error}). Press Esc and try again.")
        elif not self.polls:
            status.update("No polls have been released yet.")
        else:
            status.update("")
            for poll in self.polls:
                body = Static(poll_table(poll), classes="poll")
                body.border_title = poll_title(poll)
                await holder.mount(body)

    def action_close(self) -> None:
        self.dismiss()
