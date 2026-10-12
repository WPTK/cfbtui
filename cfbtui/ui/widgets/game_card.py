"""GameCard: one game as a compact card.

Three lines inside a border: the away row, the home row, and a status line.
Team rows are painted in the team's color. Everything the card says is first
reduced to a :class:`CardModel` by :func:`build_card`, a pure function of the
game and the glyph set, so tests assert on plain text and the widget only
paints.

Border title: ``UPSET WATCH`` or ``UPSET`` from the upset verdict, and
``RED ZONE`` while the offense is inside the 20. The border also changes with
the classes ``live``, ``final``, ``pregame``, ``upset`` and ``flash``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from rich.console import Group, RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from cfbtui.espn.models import Competitor, Game
from cfbtui.state.upset import UpsetVerdict
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.labels import period_name, pretty_status
from cfbtui.ui.theme import foreground_for

EASTERN = ZoneInfo("America/New_York")
FLASH_SECONDS = 3.0
# A kickoff further out than this shows its date, so next week's game never looks like this week's.
FAR_KICKOFF = timedelta(days=5)


@dataclass(frozen=True, slots=True)
class RowModel:
    left: str
    right: str
    score: str
    team_id: str
    background: str
    foreground: str
    bold: bool = False
    dim: bool = False
    flash: bool = False

    def plain(self, width: int) -> str:
        right = f"{self.right}{self.score}"
        pad = max(1, width - len(self.left) - len(right))
        return f"{self.left}{' ' * pad}{right}"


@dataclass(frozen=True, slots=True)
class CardModel:
    title: str
    rows: tuple[RowModel, RowModel]  # away, home
    status: str
    extra: str
    classes: tuple[str, ...] = field(default_factory=tuple)

    def lines(self, width: int = 34) -> list[str]:
        """The three content lines as plain text, for tests and logs."""
        status = self.status
        pad = max(1, width - len(status) - len(self.extra))
        return [
            self.rows[0].plain(width),
            self.rows[1].plain(width),
            f"{status}{' ' * pad}{self.extra}" if self.extra else status,
        ]


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


def _extra_text(game: Game) -> str:
    if game.is_pregame:
        if game.odds and game.odds.details:
            return game.odds.details
        return game.broadcasts[0] if game.broadcasts else ""
    if game.is_live and game.situation and game.situation.down_distance_text:
        return game.situation.down_distance_text
    return ""


def _row(
    game: Game,
    side: Competitor,
    glyphs: Glyphs,
    flash_team_id: str | None,
    favorite: bool = False,
) -> RowModel:
    live = game.is_live
    sit = game.situation if live else None
    lead = glyphs.possession if sit is not None and sit.possession == side.id else " "
    rank = f"{glyphs.rank}{side.rank}" if side.rank is not None else ""
    record = f" {side.record}" if side.record else ""
    star = glyphs.favorite if favorite else " "
    left = f" {lead}{star}{rank:>3} {side.abbreviation:<5}{record}"
    timeouts = ""
    if sit is not None:
        remaining = sit.home_timeouts if side.home_away == "home" else sit.away_timeouts
        timeouts = glyphs.timeouts(remaining)
    score = "" if game.is_pregame else str(side.score)
    right = f"{timeouts} " if timeouts else ""
    background = side.team.color
    winner = game.is_final and game.leader is not None and game.leader.id == side.id
    loser = game.is_final and game.trailer is not None and game.trailer.id == side.id
    leading = live and game.leader is not None and game.leader.id == side.id
    return RowModel(
        left=left,
        right=right,
        score=f"{score:>3} " if score else "    ",
        team_id=side.id,
        background=background,
        foreground=foreground_for(background),
        bold=winner or leading,
        dim=loser,
        flash=flash_team_id == side.id,
    )


def build_card(
    game: Game,
    glyphs: Glyphs,
    *,
    verdict: UpsetVerdict | None = None,
    flash_team_id: str | None = None,
    favorites: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> CardModel:
    title_parts: list[str] = []
    classes: list[str] = []
    if verdict is not None:
        if verdict.confirmed:
            title_parts.append(f"{glyphs.upset} UPSET")
        else:
            title_parts.append(f"{glyphs.upset_watch} UPSET WATCH")
        classes.append("upset")
    if game.is_live and game.situation is not None and game.situation.is_red_zone:
        title_parts.append(f"{glyphs.red_zone} RED ZONE")
        classes.append("redzone")
    classes.append("live" if game.is_live else "pregame" if game.is_pregame else "final")
    if flash_team_id is not None:
        classes.append("flash")
    return CardModel(
        title=" ".join(title_parts),
        rows=(
            _row(game, game.away, glyphs, flash_team_id, game.away.id in favorites),
            _row(game, game.home, glyphs, flash_team_id, game.home.id in favorites),
        ),
        status=status_text(game, glyphs, now or datetime.now(UTC)),
        extra=_extra_text(game),
        classes=tuple(classes),
    )


def render_card(model: CardModel) -> RenderableType:
    parts: list[RenderableType] = []
    for row in model.rows:
        style = Style(color=row.foreground, bgcolor=row.background, bold=row.bold, dim=row.dim)
        score_style = style + Style(reverse=True, bold=True) if row.flash else style
        # The style goes on the columns and the text: a Table's own style is not carried to its cells.
        table = Table(show_header=False, show_edge=False, box=None, padding=0, expand=True)
        table.add_column(ratio=1, no_wrap=True, overflow="ellipsis", style=style)
        table.add_column(justify="right", no_wrap=True, style=style)
        table.add_row(
            Text(row.left, style=style),
            Text.assemble((row.right, style), (row.score, score_style)),
        )
        parts.append(table)
    status = Table(show_header=False, show_edge=False, box=None, padding=0, expand=True)
    status.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    status.add_column(justify="right", no_wrap=True, style="dim")
    status.add_row(Text(f" {model.status}"), Text(f"{model.extra} " if model.extra else ""))
    parts.append(status)
    return Group(*parts)


class GameCard(Static):
    """A card that repaints itself from a game, a glyph set and a few flags."""

    DEFAULT_CSS = """
    GameCard {
        height: 5;
        width: 1fr;
        border: round $panel-lighten-2;
        border-title-color: $text;
        border-title-style: bold;
        padding: 0;
    }
    GameCard.live { border: round $success; }
    GameCard.final { border: round $panel; }
    GameCard.upset { border: heavy $warning; border-title-color: $warning; }
    GameCard.redzone { border-title-color: $error; }
    GameCard.flash { border: double $accent; }
    GameCard.old { text-opacity: 55%; }
    GameCard:focus { border: double $primary; }
    """

    can_focus = True

    def __init__(
        self,
        game: Game,
        glyphs: Glyphs,
        *,
        verdict: UpsetVerdict | None = None,
        favorites: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        self.favorites = favorites
        self.game = game
        self.glyphs = glyphs
        self.verdict = verdict
        self.data_old = False
        self._flash_team: str | None = None
        self._flash_timer = None
        self.model: CardModel | None = None
        self.repaint()

    @property
    def game_id(self) -> str:
        return self.game.id

    def show(
        self,
        game: Game,
        glyphs: Glyphs,
        verdict: UpsetVerdict | None,
        *,
        data_old: bool = False,
        favorites: frozenset[str] | None = None,
    ) -> None:
        favorites = self.favorites if favorites is None else favorites
        unchanged = (
            game == self.game
            and favorites == self.favorites
            and glyphs is self.glyphs
            and verdict == self.verdict
            and data_old == self.data_old
        )
        self.game, self.glyphs, self.verdict, self.data_old = game, glyphs, verdict, data_old
        self.favorites = favorites
        if not unchanged:  # most polls change a handful of the 60-odd games
            self.repaint()

    def set_data_old(self, data_old: bool) -> None:
        if data_old != self.data_old:
            self.data_old = data_old
            self.repaint()

    def flash(self, team_id: str) -> None:
        """Highlight the scoring side's score for a few seconds."""
        self._flash_team = team_id
        self.repaint()
        if self.is_attached:
            self._restart_flash_timer()

    def on_mount(self) -> None:
        if self._flash_team is not None:  # flashed before it was mounted
            self._restart_flash_timer()

    def _restart_flash_timer(self) -> None:
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(FLASH_SECONDS, self._end_flash)

    def _end_flash(self) -> None:
        self._flash_team = None
        self.repaint()

    def repaint(self) -> None:
        model = build_card(
            self.game, self.glyphs, verdict=self.verdict, flash_team_id=self._flash_team, favorites=self.favorites
        )
        self.model = model
        self.border_title = model.title
        for name in ("live", "final", "pregame", "upset", "redzone", "flash"):
            self.set_class(name in model.classes, name)
        self.set_class(self.data_old, "old")
        self.update(render_card(model))
