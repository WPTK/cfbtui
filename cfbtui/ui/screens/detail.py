"""DetailScreen: one game's scoring plays and win probability, from the ``summary`` endpoint.

The screen owns a small fetch loop beside the app's poll scheduler: one fetch
on open, then a refresh every ``live_refresh`` seconds until the game is final.
The loop is a worker of the screen, so popping the screen cancels it. The app
feeds in fresher scoreboard data with :meth:`DetailScreen.update_game`, so the
header keeps moving even between summary fetches.

Rendering is split out as pure functions of the game, the summary and a glyph
table (:func:`win_bar`, :func:`play_line`, :func:`build_detail`, plus the stats sections:
:func:`linescore_table`, :func:`stats_block`, :func:`win_sparkline`), each ``None`` when ESPN sent nothing.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Static

from cfbtui.espn.client import EspnError
from cfbtui.espn.models import Competitor, Game, ScoringPlay, Summary, TeamStat
from cfbtui.ui.glyphs import Glyphs
from cfbtui.ui.labels import period_name, status_text
from cfbtui.ui.theme import hex_color, team_style

LIVE_REFRESH = 20.0
IDLE_REFRESH = 60.0
BAR_WIDTH = 30
DEFAULT_WIDTH = 60
LABEL_WIDTH = 11
VALUE_WIDTH = 6
# (ESPN stat name, label, how the bar measures it)
STAT_ROWS = (
    ("totalYards", "Total yds", "number"),
    ("netPassingYards", "Pass yds", "number"),
    ("rushingYards", "Rush yds", "number"),
    ("firstDowns", "1st downs", "number"),
    ("thirdDownEff", "3rd down", "made"),
    ("fourthDownEff", "4th down", "made"),
    ("turnovers", "Turnovers", "number"),
    ("totalPenaltiesYards", "Penalties", "penalty"),
    ("possessionTime", "Possession", "clock"),
)


class SummarySource(Protocol):
    async def summary(self, event_id: str) -> Summary: ...


def win_bar(home_probability: float | None, game: Game, glyphs: Glyphs, width: int = BAR_WIDTH) -> str | None:
    """``TEX 38% ░░░░░████████ 62% OU``; the home side fills from the right. ``None`` without a probability."""
    if home_probability is None:
        return None
    home = min(1.0, max(0.0, home_probability))
    filled = round(home * width)
    bar = glyphs.bar_empty * (width - filled) + glyphs.bar_full * filled
    away_pct = round((1 - home) * 100)
    home_pct = round(home * 100)
    return f"{game.away.abbreviation} {away_pct}% {bar} {home_pct}% {game.home.abbreviation}"


def _team_text(text: str, color: str, **attrs: bool) -> Text:
    return Text(text, style=team_style(color, **attrs))


def linescore_table(game: Game, summary: Summary, glyphs: Glyphs) -> Text | None:
    """Per-period scores, one row a team: ``TEX    7 10  0  7  24``. ``None`` without linescores."""
    away, home = summary.away_linescores, summary.home_linescores
    if not away or not home:
        return None
    periods = max(len(away), len(home))
    out = Text("".ljust(6))
    for n in range(1, periods + 1):
        out.append(period_name(n).rjust(4), style="bold")
    out.append("   T".rjust(5), style="bold")
    for side, scores in ((game.away, away), (game.home, home)):
        out.append("\n")
        out.append_text(_team_text(f" {side.team.abbreviation:<5}", side.team.color, bold=True))
        for n in range(periods):
            out.append((str(scores[n]) if n < len(scores) else glyphs.sep.strip()).rjust(4))
        out.append(str(sum(scores)).rjust(5), style="bold")
    return out


def _stat_number(stat: TeamStat | None, kind: str) -> float | None:
    """What the bar measures: the first count (``3-14`` is 3 made), penalty yards, or clock seconds."""
    if stat is None:
        return None
    parts = stat.display_value.replace(":", "-").split("-")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if kind == "clock" and len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if kind == "penalty" and len(nums) == 2:
        return nums[1]
    return nums[0]


def stats_block(game: Game, summary: Summary, glyphs: Glyphs, width: int = DEFAULT_WIDTH) -> Text | None:
    """Mirrored bars, away growing leftwards from the middle and home rightwards, scaled to ``width``."""
    by_team = {t.team_id: {s.name: s for s in t.stats} for t in summary.team_stats}
    away_stats, home_stats = by_team.get(game.away.team.id), by_team.get(game.home.team.id)
    if not away_stats or not home_stats:
        return None
    half = max(3, (width - LABEL_WIDTH - 2 * VALUE_WIDTH - 4) // 2)
    pad = VALUE_WIDTH + 1 + half
    away_abbr, home_abbr = game.away.team.abbreviation, game.home.team.abbreviation
    out = Text(" " * (LABEL_WIDTH + 1 + pad - len(away_abbr)))
    out.append_text(_team_text(away_abbr, game.away.team.color, bold=True))
    out.append("|")
    out.append_text(_team_text(home_abbr, game.home.team.color, bold=True))
    wrote = False
    for name, label, kind in STAT_ROWS:
        a, h = away_stats.get(name), home_stats.get(name)
        na, nh = _stat_number(a, kind), _stat_number(h, kind)
        if a is None or h is None or na is None or nh is None:
            continue
        scale = max(na, nh)
        fill_a = round(na / scale * half) if scale else 0
        fill_h = round(nh / scale * half) if scale else 0
        out.append("\n" + label.ljust(LABEL_WIDTH) + " ")
        out.append_text(_team_text(a.display_value.rjust(VALUE_WIDTH), game.away.team.color))
        out.append(" " + glyphs.bar_empty * (half - fill_a))
        out.append(glyphs.bar_full * fill_a, style=Style(color=hex_color(game.away.team.color)))
        out.append("|")
        out.append(glyphs.bar_full * fill_h, style=Style(color=hex_color(game.home.team.color)))
        out.append(glyphs.bar_empty * (half - fill_h) + " ")
        out.append_text(_team_text(h.display_value.ljust(VALUE_WIDTH), game.home.team.color))
        wrote = True
    return out if wrote else None


def win_sparkline(game: Game, summary: Summary, glyphs: Glyphs, width: int = BAR_WIDTH) -> Text | None:
    """The whole win-probability history as one row, home high; each step in the leader's colour."""
    series = summary.winprobability
    if len(series) < 2:
        return None
    n = min(len(series), max(2, width))
    levels = len(glyphs.spark) - 1
    out = Text(f"{game.away.team.abbreviation} ")
    for i in range(n):
        p = min(1.0, max(0.0, series[round(i * (len(series) - 1) / (n - 1))]))
        side = game.home if p >= 0.5 else game.away
        out.append(glyphs.spark[round(p * levels)], style=Style(color=hex_color(side.team.color)))
    out.append(f" {game.home.team.abbreviation}")
    return out


def _kind_icon(play: ScoringPlay, glyphs: Glyphs) -> str:
    key = f"{play.scoring_type} {play.type_text}".lower()
    if "touchdown" in key:
        return glyphs.touchdown
    if "field" in key:
        return glyphs.field_goal
    if "safety" in key:
        return glyphs.safety
    if "two" in key or "2-pt" in key or "2pt" in key:
        return glyphs.two_point
    if "extra" in key or "pat" in key:
        return glyphs.pat
    return glyphs.score


def play_line(play: ScoringPlay, game: Game, glyphs: Glyphs) -> str:
    """``Q1 6:56  ★ TEX  Cam Coleman 41 Yd pass ...  [TEX 7 - OU 0]``."""
    when = f"{period_name(play.period)} {play.clock}" if play.period else play.clock
    team = play.team_abbreviation or "?"
    score = f"{game.away.abbreviation} {play.away_score} - {game.home.abbreviation} {play.home_score}"
    text = f"  {play.text}" if play.text else ""
    return f"{when:<8} {_kind_icon(play, glyphs)} {team:<5}{text}  [{score}]".rstrip()


def header_lines(game: Game, glyphs: Glyphs) -> list[str]:
    def side(c: Competitor) -> str:
        rank = f"{glyphs.rank}{c.rank} " if c.rank is not None else ""
        record = f"  {c.record}" if c.record else ""
        score = "" if game.is_pregame else f"  {c.score}"
        return f"{rank}{c.team.display_name}{record}{score}"

    lines = [side(game.away), f"{glyphs.at} {side(game.home)}", status_text(game, glyphs, datetime.now(UTC))]
    if game.venue:
        lines.append(game.venue)
    return lines


def build_detail(
    game: Game, summary: Summary | None, glyphs: Glyphs, *, error: str | None = None, width: int = DEFAULT_WIDTH
) -> RenderableType:
    parts: list[RenderableType] = []
    head = Text()
    for i, line in enumerate(header_lines(game, glyphs)):
        if i < 2:
            side = game.away if i == 0 else game.home
            head.append(f" {line} ", style=team_style(side.team.color, bold=True))
            head.append("\n")
        else:
            head.append(line + "\n", style="dim")
    parts.append(head)
    if summary is not None:
        bar = win_bar(summary.home_win_probability, game, glyphs)
        if bar:
            parts.append(Text(bar + "\n"))
        spark = win_sparkline(game, summary, glyphs, min(BAR_WIDTH, width - 10))
        if spark:
            parts.extend([Text("Win probability, whole game", style="dim"), spark, Text()])
        for title, section in (
            ("Score by period", linescore_table(game, summary, glyphs)),
            ("Team stats", stats_block(game, summary, glyphs, width)),
        ):
            if section:
                parts.extend([Text(title, style="bold underline"), section, Text()])
    if error:
        parts.append(Text(f"{glyphs.error} Could not refresh ({error}). Trying again.\n", style="yellow"))
    if summary is None:
        if not error:
            parts.append(Text(f"{glyphs.loading} Loading scoring plays", style="dim"))
    elif not summary.scoring_plays:
        parts.append(Text("No scoring yet.", style="dim"))
    else:
        parts.append(Text("Scoring plays", style="bold underline"))
        body = Text()
        for play in summary.scoring_plays:
            body.append(play_line(play, game, glyphs) + "\n")
        parts.append(body)
    return Group(*parts)


class DetailScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
    ]

    DEFAULT_CSS = """
    DetailScreen { layout: vertical; }
    DetailScreen > VerticalScroll { height: 1fr; padding: 1 2; }
    """

    def __init__(
        self,
        client: SummarySource,
        game: Game,
        glyphs: Glyphs,
        *,
        live_refresh: float = LIVE_REFRESH,
        idle_refresh: float = IDLE_REFRESH,
    ) -> None:
        super().__init__()
        self.client = client
        self.game = game
        self.glyphs = glyphs
        self.live_refresh = live_refresh
        self.idle_refresh = idle_refresh
        self.summary: Summary | None = None
        self.error: str | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._paint()
        self.run_worker(self._loop(), name="detail", group="detail", exclusive=True)

    def _paint(self) -> None:
        try:
            body = self.query_one("#detail", Static)
        except NoMatches:
            # Escape removes the screen's widgets before its Unmount cancels the fetch worker, so a fetch that
            # was in flight can come back to an empty screen. Nothing to paint on; the worker is about to go.
            return
        body.update(build_detail(self.game, self.summary, self.glyphs, error=self.error, width=self._body_width()))

    def _body_width(self) -> int:
        return self.size.width - 6 if self.size.width > 6 else DEFAULT_WIDTH

    def on_resize(self) -> None:
        self._paint()

    def update_game(self, game: Game) -> None:
        """Fresher scoreboard data for this game, from the app's poll."""
        if game.id == self.game.id:
            self.game = game
            self._paint()

    def set_glyphs(self, glyphs: Glyphs) -> None:
        self.glyphs = glyphs
        self._paint()

    @property
    def done(self) -> bool:
        if self.game.is_final:
            return True
        return self.summary is not None and self.summary.status.completed

    async def _loop(self) -> None:
        while True:
            await self._fetch_once()
            if self.done or not self.is_attached:
                return
            await asyncio.sleep(self.live_refresh if self.game.is_live else self.idle_refresh)

    async def _fetch_once(self) -> None:
        try:
            summary = await self.client.summary(self.game.id)
        except EspnError as exc:
            self.error = str(exc) or type(exc).__name__
        except Exception as exc:  # a malformed payload must not kill the screen
            self.error = f"{type(exc).__name__}: {exc}"
        else:
            self.summary = summary
            self.error = None
        self._paint()

    def action_close(self) -> None:
        self.dismiss()
