"""GameCard: one game as a compact card.

Three lines inside a border: the away row, the home row, and a status line.
Team rows are painted in the team's color. Everything the card says is first
reduced to a :class:`CardModel` by :func:`build_card`, a pure function of the
game and the glyph set, so tests assert on plain text and the widget only
paints.

Border title: ``UPSET WATCH`` or ``UPSET`` from the upset verdict, and
``RED ZONE`` while the offense is inside the 20. The border also changes with
the classes ``live``, ``final``, ``pregame``, ``upset`` and ``flash``.
A pulse (:meth:`GameCard.pulse`) adds ``pulsing``, ``pulse-<kind>`` and, on the bright
half of each breath, ``pulse-hi``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from rich.console import Group, RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.timer import Timer
from textual.widgets import Static

from cfbtui.espn.models import Competitor, Game
from cfbtui.state.upset import UpsetVerdict
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.labels import status_text
from cfbtui.ui.theme import foreground_for, team_style

FLASH_SECONDS = 3.0
PULSE_HALF_SECONDS = 0.75  # one breath (dim, then bright) is 1.5 s
PULSE_CYCLES = 5
PULSE_KINDS = ("redzone", "upset", "overtime", "final", "locate")


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
    if game.in_red_zone:
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


def compact_line(
    game: Game,
    glyphs: Glyphs,
    *,
    verdict: UpsetVerdict | None = None,
    flash_team_id: str | None = None,
    favorites: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> Text:
    """The list layout: both teams in their colors, then status, odds or down and distance, upset flag."""
    line = Text(" ")
    for i, side in enumerate((game.away, game.home)):
        row = _row(game, side, glyphs, flash_team_id, side.id in favorites)
        style = team_style(row.background, bold=row.bold, dim=row.dim)
        if row.flash:
            style += Style(reverse=True)
        score = row.score.strip()
        line.append(f"{row.left.strip():<14}{score:>3} " if score else f"{row.left.strip():<14}    ", style=style)
        if i == 0:
            line.append(f" {glyphs.at} ")
    line.append(f"  {status_text(game, glyphs, now or datetime.now(UTC))}")
    extra = _extra_text(game)
    if extra:
        line.append(f"  {extra}", style="dim")
    if verdict is not None:
        label = f"  {glyphs.upset} UPSET" if verdict.confirmed else f"  {glyphs.upset_watch} UPSET WATCH"
        line.append(label, style="bold yellow")
    if game.in_red_zone:
        line.append(f"  {glyphs.red_zone} RED ZONE", style="bold red")
    return line


def render_card(model: CardModel) -> RenderableType:
    parts: list[RenderableType] = []
    for row in model.rows:
        style = team_style(row.background, bold=row.bold, dim=row.dim)
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
    GameCard.pulsing { border: heavy $panel-lighten-2; }
    GameCard.pulse-redzone { border: heavy $error 45%; }
    GameCard.pulse-redzone.pulse-hi { border: heavy $error; }
    GameCard.pulse-upset { border: heavy $warning 45%; }
    GameCard.pulse-upset.pulse-hi { border: heavy $warning; }
    GameCard.pulse-overtime { border: heavy magenta 45%; }
    GameCard.pulse-overtime.pulse-hi { border: heavy magenta; }
    GameCard.pulse-final { border: heavy $success 45%; }
    GameCard.pulse-final.pulse-hi { border: heavy white; }
    GameCard.pulse-locate { border: heavy $accent 45%; }
    GameCard.pulse-locate.pulse-hi { border: heavy $accent; }
    GameCard.flash { border: double $accent; }
    GameCard.old { text-opacity: 55%; }
    GameCard.compact { height: 1; border: none; }
    GameCard.compact:focus { border: none; background: $boost; text-style: bold; }
    GameCard:focus { border: double $primary; }
    GameCard.pulsing:focus { border: double $primary 60%; }
    GameCard.pulsing.pulse-hi:focus { border: double $primary; }
    GameCard.compact.pulsing { border: none; }
    GameCard.compact.pulse-hi { background: $boost; text-style: bold; }
    """

    can_focus = True

    def __init__(
        self,
        game: Game,
        glyphs: Glyphs,
        *,
        verdict: UpsetVerdict | None = None,
        favorites: frozenset[str] = frozenset(),
        compact: bool = False,
    ) -> None:
        super().__init__()
        self.compact = compact
        self.set_class(compact, "compact")
        self.favorites = favorites
        self.game = game
        self.glyphs = glyphs
        self.verdict = verdict
        self.data_old = False
        self._flash_team: str | None = None
        self._flash_timer: Timer | None = None
        self._pulse_timer: Timer | None = None
        self._pulse_kind: str | None = None
        self._pulse_steps = 0
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
        compact: bool | None = None,
    ) -> None:
        favorites = self.favorites if favorites is None else favorites
        compact = self.compact if compact is None else compact
        unchanged = (
            compact == self.compact
            and game == self.game
            and favorites == self.favorites
            and glyphs is self.glyphs
            and verdict == self.verdict
            and data_old == self.data_old
        )
        self.game, self.glyphs, self.verdict, self.data_old = game, glyphs, verdict, data_old
        self.favorites = favorites
        self.compact = compact
        self.set_class(compact, "compact")
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

    def pulse(self, kind: str) -> None:
        """Breathe the border in ``kind``'s colour (and a heavy border, for monochrome) for a few seconds.

        Slower and fainter than :meth:`flash`. A second pulse restarts the first rather than stacking.
        """
        if kind not in PULSE_KINDS:
            raise ValueError(f"unknown pulse kind {kind!r}")
        self._clear_pulse()
        self._pulse_kind = kind
        self._pulse_steps = PULSE_CYCLES * 2
        self.add_class("pulsing", f"pulse-{kind}", "pulse-hi")
        if self.is_attached:
            self._start_pulse_timer()

    def _start_pulse_timer(self) -> None:
        self._pulse_timer = self.set_interval(PULSE_HALF_SECONDS, self._pulse_step)

    def _pulse_step(self) -> None:
        self._pulse_steps -= 1
        if self._pulse_steps <= 0:
            self._clear_pulse()
        else:
            self.toggle_class("pulse-hi")

    def _clear_pulse(self) -> None:
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        if self._pulse_kind is not None:
            self.remove_class("pulsing", f"pulse-{self._pulse_kind}", "pulse-hi")
            self._pulse_kind = None

    def on_mount(self) -> None:
        if self._flash_team is not None:  # flashed before it was mounted
            self._restart_flash_timer()
        if self._pulse_kind is not None:  # pulsed before it was mounted
            self._start_pulse_timer()

    def _restart_flash_timer(self) -> None:
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(FLASH_SECONDS, self._end_flash)

    def _end_flash(self) -> None:
        self._flash_team = None
        self.repaint()

    def repaint(self) -> None:
        self.set_class(self.data_old, "old")
        if self.compact:
            self.model = None
            self.border_title = ""
            for name in ("live", "final", "pregame", "upset", "redzone", "flash"):
                self.set_class(False, name)
            self.update(
                compact_line(
                    self.game,
                    self.glyphs,
                    verdict=self.verdict,
                    flash_team_id=self._flash_team,
                    favorites=self.favorites,
                )
            )
            return
        model = build_card(
            self.game, self.glyphs, verdict=self.verdict, flash_team_id=self._flash_team, favorites=self.favorites
        )
        self.model = model
        self.border_title = model.title
        for name in ("live", "final", "pregame", "upset", "redzone", "flash"):
            self.set_class(name in model.classes, name)
        self.set_class(self.data_old, "old")
        self.update(render_card(model))
