"""The upset rule: who is the favorite, who is the underdog, and is the underdog winning.

Rank comes from the scoreboard's ``curatedRank`` first (AP by default). When
that is missing, a rankings payload can fill the gap: pass the tuple from
:func:`cfbtui.espn.parse.parse_rankings` and the poll ``type`` to prefer.

Semantics, in order:

- Tied game: no verdict.
- Both unranked: no verdict.
- Favorite is the better-ranked side; unranked counts as worse than any rank.
- Equal ranks (only possible when both are unranked, already excluded, or
  when ESPN duplicates a number): no verdict.
- Verdict is a *watch* while the game is live and *confirmed* once final.
  Pregame games never produce a verdict.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from cfbtui.espn.models import Competitor, Game, GameState, Ranking

DEFAULT_POLL = "ap"


@dataclass(frozen=True, slots=True)
class UpsetVerdict:
    underdog: Competitor
    favorite: Competitor
    underdog_rank: int | None
    favorite_rank: int
    confirmed: bool
    margin: int

    @property
    def watch(self) -> bool:
        return not self.confirmed


class UpsetRule:
    """Pure: :meth:`evaluate` reads a :class:`Game` and returns a verdict or ``None``."""

    def __init__(
        self,
        rankings: Iterable[Ranking] | None = None,
        *,
        poll: str = DEFAULT_POLL,
    ) -> None:
        self.poll = poll
        self._ranking: Ranking | None = None
        self.set_rankings(rankings)

    def set_rankings(self, rankings: Iterable[Ranking] | None) -> None:
        """Choose the poll of type ``self.poll`` from a rankings payload (or forget it)."""
        self._ranking = None
        if rankings is None:
            return
        for r in rankings:
            if r.type == self.poll:
                self._ranking = r
                return

    @property
    def ranking(self) -> Ranking | None:
        return self._ranking

    def rank_of(self, competitor: Competitor) -> int | None:
        """``curatedRank`` when present, else the chosen poll, else unranked."""
        if competitor.rank is not None:
            return competitor.rank
        if self._ranking is not None:
            return self._ranking.rank_of(competitor.id)
        return None

    def evaluate(self, game: Game) -> UpsetVerdict | None:
        if game.state == GameState.PRE or game.is_tied:
            return None
        leader, trailer = game.leader, game.trailer
        if leader is None or trailer is None:
            return None
        lead_rank = self.rank_of(leader)
        trail_rank = self.rank_of(trailer)
        if trail_rank is None:
            return None  # the trailing side is unranked; nobody to upset
        if lead_rank is not None and lead_rank <= trail_rank:
            return None  # the better-ranked side leads, or ranks tie
        return UpsetVerdict(
            underdog=leader,
            favorite=trailer,
            underdog_rank=lead_rank,
            favorite_rank=trail_rank,
            confirmed=game.is_final,
            margin=game.margin,
        )
