"""Discord-ready text for one game or a whole board. Pure functions; no clipboard here.

Discord renders Markdown, emoji and plain unicode but not Nerd Font glyphs, so
callers pass the ``unicode`` set (or ``ascii``), never ``nerd``.

``format_game`` is one Markdown line with the winner or leader in bold.
``format_board`` is a code block (so the columns line up; Discord does not
render Markdown inside one) and is split into several messages, each at most
:data:`DISCORD_LIMIT` characters, breaking only between games.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from cfbtui.espn.models import Competitor, Game
from cfbtui.ui.glyphs import UNICODE, Glyphs
from cfbtui.ui.widgets.game_card import status_text

DISCORD_LIMIT = 2000
FENCE = "```"

_MARKDOWN_CHARS = "\\*_~`|>"


def escape(text: str) -> str:
    """Backslash-escape the characters Discord would read as Markdown."""
    return "".join(f"\\{c}" if c in _MARKDOWN_CHARS else c for c in text)


def _side(side: Competitor, glyphs: Glyphs) -> str:
    rank = f"{glyphs.rank}{side.rank} " if side.rank is not None else ""
    return f"{rank}{side.abbreviation}"


def _status(game: Game, glyphs: Glyphs, now: datetime | None) -> str:
    return status_text(game, glyphs, now)


def format_game(game: Game, glyphs: Glyphs = UNICODE, *, now: datetime | None = None) -> str:
    """One Markdown line: ``**#2 TEX** 24 @ OU 27 · ■ Final``. Pregame games carry no score."""
    now = now or datetime.now(UTC)
    bold = game.leader if not game.is_pregame else None

    def part(side: Competitor) -> str:
        name = escape(_side(side, glyphs))
        name = f"**{name}**" if bold is not None and bold.id == side.id else name
        return name if game.is_pregame else f"{name} {side.score}"

    sep = f" {glyphs.sep.strip()} " if glyphs.sep.strip() else " "
    return f"{part(game.away)} {glyphs.at} {part(game.home)}{sep}{escape(_status(game, glyphs, now))}"


def _board_lines(games: Sequence[Game], glyphs: Glyphs, now: datetime | None) -> list[str]:
    width = max(len(_side(side, glyphs)) for game in games for side in (game.away, game.home))
    lines = []
    for game in games:
        away, home = _side(game.away, glyphs), _side(game.home, glyphs)
        if game.is_pregame:
            scores = ("", "")
        else:
            scores = (str(game.away.score), str(game.home.score))
        line = (
            f"{away:<{width}} {scores[0]:>3}  {glyphs.at}  {home:<{width}} {scores[1]:>3}   "
            f"{_status(game, glyphs, now)}"
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
    room = limit - 2 * len(FENCE) - 2  # the fences and their two newlines
    if title:
        lines.insert(0, title.replace(FENCE, "'''"))
    lines = [line if len(line) <= room else line[: room - 1] + glyphs.loading for line in lines]
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
