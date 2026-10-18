"""Discord-ready text for one game or a whole board. Pure functions; no clipboard here.

Discord renders Markdown, emoji and plain unicode but not Nerd Font glyphs, so
callers pass the ``unicode`` set (or ``ascii``), never ``nerd``.

``format_game`` is one Markdown line with the winner or leader in bold.
``format_board`` is a code block (so the columns line up; Discord does not
render Markdown inside one) and is split into several messages, each at most
:data:`DISCORD_LIMIT` characters, breaking only between games. ``format_poll`` is one ranking poll, the same way.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from cfbtui.espn.models import Competitor, Game, Ranking
from cfbtui.ui.glyphs import UNICODE, Glyphs
from cfbtui.ui.labels import poll_title, status_text, trend_text

DISCORD_LIMIT = 2000
FENCE = "```"

_MARKDOWN_CHARS = "\\*_~`|>"


def escape(text: str) -> str:
    """Backslash-escape the characters Discord would read as Markdown."""
    return "".join(f"\\{c}" if c in _MARKDOWN_CHARS else c for c in text)


def _side(side: Competitor, glyphs: Glyphs) -> str:
    rank = f"{glyphs.rank}{side.rank} " if side.rank is not None else ""
    return f"{rank}{side.abbreviation}"


def format_game(game: Game, glyphs: Glyphs = UNICODE, *, now: datetime | None = None) -> str:
    """One Markdown line: ``**#2 TEX** 24 @ OU 27 · ■ Final``. Pregame games carry no score."""
    now = now or datetime.now(UTC)
    bold = game.leader if not game.is_pregame else None

    def part(side: Competitor) -> str:
        name = escape(_side(side, glyphs))
        name = f"**{name}**" if bold is not None and bold.id == side.id else name
        return name if game.is_pregame else f"{name} {side.score}"

    sep = f" {glyphs.sep.strip()} " if glyphs.sep.strip() else " "
    return f"{part(game.away)} {glyphs.at} {part(game.home)}{sep}{escape(status_text(game, glyphs, now))}"


def _board_lines(games: Sequence[Game], glyphs: Glyphs, now: datetime | None) -> list[str]:
    width = max(len(_side(side, glyphs)) for game in games for side in (game.away, game.home))
    lines = []
    for game in games:
        away, home = _side(game.away, glyphs), _side(game.home, glyphs)
        scores = ("", "") if game.is_pregame else (str(game.away.score), str(game.home.score))
        line = (
            f"{away:<{width}} {scores[0]:>3}  {glyphs.at}  {home:<{width}} {scores[1]:>3}   "
            f"{status_text(game, glyphs, now)}"
        )
        lines.append(line.rstrip().replace(FENCE, "'''"))
    return lines


def format_board(
    games: Iterable[Game],
    glyphs: Glyphs = UNICODE,
    *,
    title: str | None = None,
    now: datetime | None = None,
    limit: int = DISCORD_LIMIT,
) -> list[str]:
    """The games, in the order given, as code-block messages of at most ``limit`` characters.

    Empty when there are no games. ``title`` heads the first message only.
    """
    games = list(games)
    if not games:
        return []
    now = now or datetime.now(UTC)
    lines = _board_lines(games, glyphs, now)
    if title:
        lines.insert(0, title.replace(FENCE, "'''"))
    return _code_messages(lines, glyphs, limit)


def _code_messages(lines: list[str], glyphs: Glyphs, limit: int) -> list[str]:
    """Pack lines into code blocks of at most ``limit`` characters, breaking only between lines."""
    room = limit - 2 * len(FENCE) - 2  # the fences and their two newlines
    cut = max(1, room - len(glyphs.loading))
    lines = [line if len(line) <= room else line[:cut] + glyphs.loading for line in lines]
    messages: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        cost = len(line) + (1 if current else 0)
        if current and size + cost > room:
            messages.append("\n".join(current))
            current, size, cost = [], 0, len(line)
        current.append(line)
        size += cost
    messages.append("\n".join(current))
    return [f"{FENCE}\n{body}\n{FENCE}" for body in messages]


def format_poll(poll: Ranking, glyphs: Glyphs = UNICODE, *, limit: int = DISCORD_LIMIT) -> list[str]:
    """One poll as code-block messages of at most ``limit`` characters; the heading leads the first.

    Columns: rank, team, record, points, change. Empty when the poll has no ranked teams.
    """
    if not poll.ranks:
        return []
    rows = [
        (
            f"{glyphs.rank}{e.rank}" if e.rank is not None else "",
            e.name + (f" ({e.first_place_votes})" if e.first_place_votes else ""),
            e.record or "",
            f"{e.points:.0f}" if e.points is not None else "",
            trend_text(e.previous, e.trend),
        )
        for e in poll.ranks
    ]
    wide = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = [
        f"{r:>{wide[0]}}  {t:<{wide[1]}}  {rec:<{wide[2]}}  {pts:>{wide[3]}}  {chg}".rstrip().replace(FENCE, "'''")
        for r, t, rec, pts, chg in rows
    ]
    lines.insert(0, poll_title(poll).replace(FENCE, "'''"))
    return _code_messages(lines, glyphs, limit)
