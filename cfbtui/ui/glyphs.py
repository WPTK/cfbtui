"""The glyph table: every icon the UI shows comes from here.

Widgets never hardcode a symbol. They hold a :class:`Glyphs` and read the
attribute they need, so switching sets (the ``g`` key) swaps every icon at
once. Four sets ship:

- ``ascii``: plain characters that survive any terminal and any font.
- ``unicode``: Basic Multilingual Plane symbols most monospace fonts carry.
- ``emoji``: colorful, double-width on most terminals; alignment is loose.
- ``nerd``: Nerd Font private-use codepoints (FontAwesome range). The default,
  because the author runs Windows Terminal with a Nerd Font.

Box-drawing borders are not here; Textual draws them and they look the same
in every set.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

from cfbtui.state.events import ScoreKind

DEFAULT_SET = "nerd"


@dataclass(frozen=True, slots=True)
class Glyphs:
    """One icon per situation. ``name`` is the set's key in :data:`GLYPH_SETS`."""

    name: str
    # game state
    live: str
    final: str
    pregame: str
    halftime: str
    kickoff: str
    period: str
    # scoring
    touchdown: str
    field_goal: str
    safety: str
    two_point: str
    pat: str
    score: str
    correction: str
    # situation
    red_zone: str
    possession: str
    timeout: str
    timeout_used: str
    upset: str
    upset_watch: str
    # data freshness
    fresh: str
    stale: str
    error: str
    loading: str
    refresh: str
    # punctuation the widgets would otherwise hardcode
    sep: str
    inferred: str
    at: str
    rank: str
    favorite: str
    bar_full: str
    bar_empty: str
    spark: str  # eight levels, lowest first

    def for_score_kind(self, kind: ScoreKind) -> str:
        """The icon for a :class:`ScoreKind`; ``score`` for the unknown kind."""
        return {
            ScoreKind.TOUCHDOWN: self.touchdown,
            ScoreKind.FIELD_GOAL: self.field_goal,
            ScoreKind.SAFETY: self.safety,
            ScoreKind.TWO_POINT: self.two_point,
            ScoreKind.PAT: self.pat,
        }.get(kind, self.score)

    def timeouts(self, remaining: int | None, total: int = 3) -> str:
        """``remaining`` of ``total`` timeouts as a row of dots; empty when unknown."""
        if remaining is None:
            return ""
        remaining = max(0, min(total, remaining))
        return self.timeout * remaining + self.timeout_used * (total - remaining)


ASCII = Glyphs(
    name="ascii",
    live="*",
    final="F",
    pregame="-",
    halftime="H",
    kickoff=">",
    period=">>",
    touchdown="#",
    field_goal="^",
    safety="!",
    two_point="=",
    pat="+",
    score="*",
    correction="<",
    red_zone="!!",
    possession=">",
    timeout="o",
    timeout_used=".",
    upset="!!!",
    upset_watch="?",
    fresh="ok",
    stale="~",
    error="x",
    loading="...",
    refresh="@",
    sep="  -  ",
    inferred="?",
    at="@",
    rank="#",
    favorite="*",
    bar_full="#",
    bar_empty="-",
    spark="_.:-=+*#",
)

UNICODE = Glyphs(
    name="unicode",
    live="●",  # ●
    final="■",  # ■
    pregame="○",  # ○
    halftime="½",  # ½
    kickoff="⚐",  # ⚐
    period="»",  # »
    touchdown="★",  # ★
    field_goal="◆",  # ◆
    safety="▲",  # ▲
    two_point="✚",  # ✚
    pat="+",
    score="•",  # •
    correction="↺",  # ↺
    red_zone="⚑",  # ⚑
    possession="▶",  # ▶
    timeout="●",  # ●
    timeout_used="○",  # ○
    upset="⚡",  # ⚡
    upset_watch="◉",  # ◉
    fresh="✔",  # ✔
    stale="⌛",  # ⌛
    error="✖",  # ✖
    loading="…",  # …
    refresh="↻",  # ↻
    sep="  ·  ",
    inferred="?",
    at="@",
    rank="#",
    favorite="★",
    bar_full="█",
    bar_empty="░",
    spark="▁▂▃▄▅▆▇█",
)

EMOJI = Glyphs(
    name="emoji",
    live="\U0001f534",  # 🔴
    final="\U0001f3c1",  # 🏁
    pregame="\U0001f552",  # 🕒
    halftime="⏸",  # ⏸
    kickoff="\U0001f680",  # 🚀
    period="⏭",  # ⏭
    touchdown="\U0001f3c8",  # 🏈
    field_goal="\U0001f3af",  # 🎯
    safety="\U0001f6e1",  # 🛡
    two_point="✌",  # ✌
    pat="\u2795",  # heavy plus sign
    score="\U0001f514",  # 🔔
    correction="↩",  # ↩
    red_zone="\U0001f525",  # 🔥
    possession="\U0001f449",  # 👉
    timeout="\U0001f7e2",  # 🟢
    timeout_used="⚪",  # ⚪
    upset="⚡",  # ⚡
    upset_watch="\U0001f440",  # 👀
    fresh="✅",  # ✅
    stale="⏳",  # ⏳
    error="❌",  # ❌
    loading="\U0001f503",  # 🔃
    refresh="\U0001f504",  # 🔄
    sep="  ·  ",
    inferred="?",
    at="@",
    rank="#",
    favorite="⭐",
    bar_full="🟩",
    bar_empty="⬜",
    spark="▁▂▃▄▅▆▇█",
)

# Nerd Fonts, FontAwesome range (U+F000..U+F2E0). Names are nf-fa-*.
NERD = Glyphs(
    name="nerd",
    live="",  # circle
    final="",  # flag_checkered
    pregame="",  # clock_o
    halftime="",  # pause
    kickoff="",  # play
    period="",  # forward
    touchdown="",  # star
    field_goal="",  # bullseye
    safety="",  # shield
    two_point="",  # plus_square
    pat="",  # plus
    score="",  # circle
    correction="",  # undo
    red_zone="",  # fire
    possession="",  # caret_right
    timeout="",  # circle
    timeout_used="",  # circle_o
    upset="",  # bolt
    upset_watch="",  # eye
    fresh="",  # check
    stale="",  # hourglass_half
    error="",  # times_circle
    loading="",  # spinner
    refresh="",  # refresh
    sep="  ·  ",
    inferred="?",
    at="@",
    rank="#",
    favorite="",
    bar_full="█",
    bar_empty="░",
    spark="▁▂▃▄▅▆▇█",
)

GLYPH_SETS: dict[str, Glyphs] = {g.name: g for g in (ASCII, UNICODE, EMOJI, NERD)}
GLYPH_SET_NAMES: tuple[str, ...] = tuple(GLYPH_SETS)
GLYPH_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Glyphs) if f.name != "name")


def get(name: str | None = None) -> Glyphs:
    """The set called ``name`` (case-insensitive); the default set when ``name`` is ``None``.

    Raises :class:`KeyError` for an unknown name so a bad config value is loud.
    """
    if name is None:
        return GLYPH_SETS[DEFAULT_SET]
    key = name.strip().lower()
    if key not in GLYPH_SETS:
        raise KeyError(f"unknown glyph set {name!r}; choose from {', '.join(GLYPH_SET_NAMES)}")
    return GLYPH_SETS[key]


def next_name(name: str) -> str:
    """The set after ``name`` in cycling order, wrapping around."""
    names = GLYPH_SET_NAMES
    try:
        index = names.index(name.strip().lower())
    except ValueError:
        return DEFAULT_SET
    return names[(index + 1) % len(names)]
