"""GameStore: keep the last known state of every game and diff each poll into events.

Policy decisions (made with Bill on 2026-10-12):

- **First sight emits for live games.** The first time a game id is seen,
  nothing is diffed, but if the game is already in progress the store emits
  the status, red-zone and upset-watch events that describe it, as if they
  had just happened. Pregame and final games are silent on first sight.
- **Score deltas are decomposed, not shrugged at.** When ESPN's ``lastPlay``
  explains the delta exactly, one precise event comes out. Otherwise the delta
  is split into the likeliest set of scoring plays (7+3, 6+3, ...) and each
  piece is emitted with ``inferred=True``.
- **Rankings are live now.** The :class:`UpsetRule` reads ``curatedRank`` and
  falls back to the AP poll from a rankings payload when that is missing.
- **Games that vanish from the feed are remembered.** ``games`` reflects the
  latest poll only, but the diff baseline keeps every id ever seen, so a game
  that flickers out of ESPN's feed and back does not re-emit its first-sight
  events or diff against nothing. Use :meth:`reset` when switching weeks.

Event order within one poll, per game: ``GameStarted``, ``Scored``/
``ScoreCorrected`` (the side ESPN's ``lastPlay`` points at goes last),
``Halftime``/``PeriodChanged``, ``RedZone``, ``StatusChanged``, ``GameFinal``,
``UpsetWatch``/``Upset``. Games are processed in feed order.
"""
from __future__ import annotations

from collections.abc import Iterable

from cfbtui.espn.models import Competitor, Game, GameState, LastPlay, Scoreboard
from cfbtui.state.events import (
    Event,
    GameFinal,
    GameStarted,
    Halftime,
    PeriodChanged,
    RedZone,
    ScoreCorrected,
    Scored,
    ScoreKind,
    StatusChanged,
    Upset,
    UpsetWatch,
)
from cfbtui.state.upset import UpsetRule

# Status names that are all "the game is being played"; moving between them is
# not worth a StatusChanged event (period and halftime events cover it).
LIVE_STATUS_NAMES = frozenset(
    {
        "STATUS_IN_PROGRESS",
        "STATUS_END_PERIOD",
        "STATUS_HALFTIME",
        "STATUS_FIRST_HALF",
        "STATUS_SECOND_HALF",
        "STATUS_END_OF_REGULATION",
        "STATUS_OVERTIME",
    }
)

# Point values a kind can plausibly carry on one play. Anything else means
# ESPN's lastPlay does not explain the delta and we fall back to decomposing.
PLAUSIBLE_POINTS: dict[ScoreKind, frozenset[int]] = {
    ScoreKind.TOUCHDOWN: frozenset({6, 7, 8}),
    ScoreKind.FIELD_GOAL: frozenset({3}),
    ScoreKind.SAFETY: frozenset({2}),
    ScoreKind.TWO_POINT: frozenset({2}),
    ScoreKind.PAT: frozenset({1}),
}

# Pieces a delta can be split into, with a cost reflecting how common each
# is in a single poll window. Lower total cost wins; ties resolve toward the
# piece listed first.
_PIECES: tuple[tuple[int, float], ...] = (
    (7, 1.0),  # TD + PAT
    (3, 1.0),  # FG
    (6, 1.5),  # TD, PAT pending or missed
    (8, 1.5),  # TD + two-point
    (2, 2.0),  # safety or lone two-point
    (1, 2.0),  # lone PAT
)


def kind_from_play(play: LastPlay, points: int) -> ScoreKind | None:
    """Read the scoring kind off ESPN's play type/text; ``None`` if it does not fit ``points``."""
    type_text = play.type_text.lower()
    text = f"{type_text} {play.text.lower()}"
    conversion = "extra point" in text or "point after" in text
    kind: ScoreKind | None = None
    if ("touchdown" in type_text and not conversion) or (
        "touchdown" in text and not conversion and "two-point" not in type_text
    ):
        kind = ScoreKind.TOUCHDOWN
    elif "field goal" in text:
        kind = ScoreKind.FIELD_GOAL
    elif "safety" in text:
        kind = ScoreKind.SAFETY
    elif "two-point" in text or "two point" in text or "2-pt" in text or "2pt" in text:
        kind = ScoreKind.TWO_POINT
    elif conversion or "kick" in text or type_text in {"pat", "xp"}:
        kind = ScoreKind.PAT
    if kind is None or points not in PLAUSIBLE_POINTS[kind]:
        return None
    return kind


def decompose(points: int, *, pat_pending: bool = False) -> list[tuple[int, ScoreKind]]:
    """Split a point delta into the likeliest scoring plays, biggest first.

    ``pat_pending`` says the team's previous score was a 6-point touchdown, so
    a 2 is a two-point conversion rather than a safety.
    """
    if points <= 0:
        return []
    best: list[float | None] = [None] * (points + 1)
    choice: list[int] = [0] * (points + 1)
    best[0] = 0.0
    for n in range(1, points + 1):
        for piece, cost in _PIECES:
            prior = best[n - piece] if piece <= n else None
            if prior is None:
                continue
            total = prior + cost
            current = best[n]
            if current is None or total < current:
                best[n], choice[n] = total, piece
    pieces: list[int] = []
    n = points
    while n > 0:
        pieces.append(choice[n])
        n -= choice[n]
    pieces.sort(reverse=True)
    out: list[tuple[int, ScoreKind]] = []
    for piece in pieces:
        if piece in (6, 7, 8):
            kind = ScoreKind.TOUCHDOWN
        elif piece == 3:
            kind = ScoreKind.FIELD_GOAL
        elif piece == 2:
            kind = ScoreKind.TWO_POINT if pat_pending else ScoreKind.SAFETY
            pat_pending = False
        else:
            kind = ScoreKind.PAT
        if piece == 6:
            pat_pending = True
        out.append((piece, kind))
    return out


class GameStore:
    def __init__(
        self,
        *,
        rule: UpsetRule | None = None,
        emit_on_first_sight: bool = True,
    ) -> None:
        self.rule = rule or UpsetRule()
        self.emit_on_first_sight = emit_on_first_sight
        self.polls = 0
        self.last_errors: list[tuple[str, Exception]] = []  # (game id, error) from the latest apply
        self._games: dict[str, Game] = {}
        self._seen: dict[str, Game] = {}
        self._pat_pending: dict[str, str] = {}  # game id -> team id owed a conversion

    # --- views ----------------------------------------------------------------

    @property
    def games(self) -> tuple[Game, ...]:
        """Games from the latest poll, in feed order."""
        return tuple(self._games.values())

    @property
    def live(self) -> tuple[Game, ...]:
        return tuple(g for g in self._games.values() if g.is_live)

    def get(self, game_id: str) -> Game | None:
        return self._games.get(game_id) or self._seen.get(game_id)

    def __len__(self) -> int:
        return len(self._games)

    def __contains__(self, game_id: object) -> bool:
        return game_id in self._games

    def reset(self) -> None:
        """Forget everything. The next poll is a first sight for every game."""
        self._games.clear()
        self._seen.clear()
        self._pat_pending.clear()
        self.polls = 0

    # --- applying polls -------------------------------------------------------

    def apply_scoreboard(self, scoreboard: Scoreboard) -> list[Event]:
        return self.apply(scoreboard.games)

    def apply(self, games: Iterable[Game]) -> list[Event]:
        events: list[Event] = []
        latest: dict[str, Game] = {}
        self.last_errors = []
        for game in games:
            latest[game.id] = game
            prev = self._seen.get(game.id)
            try:
                if prev is None:
                    new = self._first_sight(game)
                elif prev is not game:
                    new = self._diff(prev, game)
                else:
                    new = []
            except Exception as exc:
                # One game that cannot be diffed must not cost the events of the others.
                # Leave its previous snapshot in place so the next poll diffs against it again.
                self.last_errors.append((game.id, exc))
                continue
            events.extend(new)
            self._seen[game.id] = game
        self._games = latest
        self.polls += 1
        return events

    def _first_sight(self, game: Game) -> list[Event]:
        if not self.emit_on_first_sight or not game.is_live:
            return []
        events: list[Event] = [GameStarted(game)]
        if game.status.is_halftime:
            events.append(Halftime(game))
        if game.situation is not None and game.situation.is_red_zone:
            events.append(RedZone(game, game.competitor(game.situation.possession)))
        verdict = self.rule.evaluate(game)
        if verdict is not None and verdict.watch:
            events.append(UpsetWatch(game, verdict.underdog, verdict.favorite))
        return events

    def _diff(self, prev: Game, cur: Game) -> list[Event]:
        events: list[Event] = []
        # pre -> in is a kickoff; pre -> final (an outage) counts too. pre -> postponed does not.
        started = prev.state == GameState.PRE and (cur.is_live or cur.is_final)
        if started:
            events.append(GameStarted(cur))

        events.extend(self._score_events(prev, cur))

        halftime = False
        if cur.is_live:
            if cur.status.is_halftime and not prev.status.is_halftime:
                halftime = True
                events.append(Halftime(cur))
            elif (
                not started
                and cur.status.period != prev.status.period
                and cur.status.period > 0
                and not cur.status.is_halftime
            ):
                events.append(PeriodChanged(cur, cur.status.period))

        if cur.is_live and cur.situation is not None and cur.situation.is_red_zone:
            ps = prev.situation
            if ps is None or not ps.is_red_zone or ps.possession != cur.situation.possession:
                events.append(RedZone(cur, cur.competitor(cur.situation.possession)))

        finished = cur.is_final and not prev.is_final
        if (
            prev.status.name != cur.status.name
            and not (started or halftime or finished)
            and not (prev.status.name in LIVE_STATUS_NAMES and cur.status.name in LIVE_STATUS_NAMES)
        ):
            events.append(StatusChanged(cur, prev.status.name, cur.status.name))

        if finished:
            self._pat_pending.pop(cur.id, None)
            events.append(GameFinal(cur, cur.leader, cur.trailer))

        before = self.rule.evaluate(prev)
        after = self.rule.evaluate(cur)
        if after is not None:
            if after.confirmed:
                if before is None or not before.confirmed:
                    events.append(Upset(cur, after.underdog, after.favorite))
            elif before is None or before.underdog.id != after.underdog.id:
                events.append(UpsetWatch(cur, after.underdog, after.favorite))
        return events

    # --- scoring --------------------------------------------------------------

    def _score_events(self, prev: Game, cur: Game) -> list[Event]:
        per_side: list[tuple[Competitor, list[Event]]] = []
        scorers = [s for s in ("away", "home") if getattr(cur, s).score > getattr(prev, s).score]
        for side in ("away", "home"):
            before: Competitor = getattr(prev, side)
            after: Competitor = getattr(cur, side)
            if after.score < before.score:
                self._pat_pending.pop(cur.id, None)
                per_side.append((after, [ScoreCorrected(cur, after, before.score, after.score)]))
            elif after.score > before.score:
                events = self._classify(cur, after, after.score - before.score, sole_scorer=len(scorers) == 1)
                per_side.append((after, events))
        # The side ESPN's lastPlay points at scored most recently, so it goes last.
        play = cur.situation.last_play if cur.situation else None
        if play is not None and play.team_id is not None and len(per_side) == 2:
            per_side.sort(key=lambda item: item[0].id == play.team_id)
        return [e for _, evs in per_side for e in evs]

    def _classify(
        self, cur: Game, team: Competitor, delta: int, *, sole_scorer: bool = True
    ) -> list[Event]:
        """Events for ``team`` gaining ``delta`` points this tick.

        A ``lastPlay`` without a team block only explains the delta when this
        is the only side that scored; otherwise it could belong to either.
        """
        play = cur.situation.last_play if cur.situation else None
        events: list[Event]
        kind = None
        if (
            play is not None
            and play.score_value == delta
            and (play.team_id == team.id or (play.team_id is None and sole_scorer))
        ):
            kind = kind_from_play(play, delta)
        if kind is not None and play is not None:
            events = [Scored(cur, team, delta, kind, text=play.text, inferred=False)]
        else:
            pending = self._pat_pending.get(cur.id) == team.id
            events = [
                Scored(cur, team, pts, piece_kind, inferred=True)
                for pts, piece_kind in decompose(delta, pat_pending=pending)
            ]
        last = events[-1] if events else None
        if isinstance(last, Scored) and last.score_kind is ScoreKind.TOUCHDOWN and last.points == 6:
            self._pat_pending[cur.id] = team.id
        elif self._pat_pending.get(cur.id) == team.id:
            self._pat_pending.pop(cur.id, None)
        return events
