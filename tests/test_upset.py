"""UpsetRule: rank semantics, watch vs confirmed, and the rankings fallback."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfbtui.espn.models import Competitor, Game, GameState, Status, Team
from cfbtui.espn.parse import parse_rankings
from cfbtui.state.upset import UpsetRule

FIXTURES = Path(__file__).parent / "fixtures"


def team(abbr: str, team_id: str) -> Team:
    return Team(id=team_id, abbreviation=abbr, display_name=abbr, short_name=abbr, color="#000000", alt_color="#ffffff")


def make_game(
    *,
    home_rank: int | None,
    away_rank: int | None,
    home_score: int,
    away_score: int,
    state: GameState = GameState.IN,
    completed: bool = False,
    home_id: str = "201",
    away_id: str = "251",
) -> Game:
    return Game(
        id="1",
        date=datetime(2026, 10, 10, tzinfo=UTC),
        name="Away at Home",
        short_name="AWY @ HOM",
        home=Competitor(team=team("HOM", home_id), home_away="home", score=home_score, rank=home_rank),
        away=Competitor(team=team("AWY", away_id), home_away="away", score=away_score, rank=away_rank),
        status=Status(state=state, completed=completed, period=4 if state != GameState.PRE else 0),
    )


@pytest.fixture(scope="module")
def rankings():
    payload = json.loads((FIXTURES / "rankings.json").read_text(encoding="utf-8"))
    return parse_rankings(payload)


def test_unranked_leading_ranked_is_a_watch():
    game = make_game(home_rank=None, away_rank=1, home_score=27, away_score=24)
    verdict = UpsetRule().evaluate(game)
    assert verdict is not None
    assert verdict.underdog is game.home
    assert verdict.favorite is game.away
    assert verdict.underdog_rank is None
    assert verdict.favorite_rank == 1
    assert verdict.watch and not verdict.confirmed
    assert verdict.margin == 3


def test_lower_rank_leading_higher_rank_is_a_watch():
    game = make_game(home_rank=12, away_rank=5, home_score=24, away_score=17)
    verdict = UpsetRule().evaluate(game)
    assert verdict is not None
    assert verdict.underdog_rank == 12
    assert verdict.favorite_rank == 5


def test_higher_rank_leading_lower_rank_is_nothing():
    game = make_game(home_rank=5, away_rank=12, home_score=24, away_score=17)
    assert UpsetRule().evaluate(game) is None


def test_ranked_leading_unranked_is_nothing():
    game = make_game(home_rank=None, away_rank=1, home_score=17, away_score=24)
    assert UpsetRule().evaluate(game) is None


def test_equal_ranks_is_nothing():
    game = make_game(home_rank=7, away_rank=7, home_score=24, away_score=17)
    assert UpsetRule().evaluate(game) is None


def test_unranked_vs_unranked_is_nothing():
    game = make_game(home_rank=None, away_rank=None, home_score=24, away_score=17)
    assert UpsetRule().evaluate(game) is None


def test_tie_is_nothing():
    game = make_game(home_rank=None, away_rank=1, home_score=17, away_score=17)
    assert UpsetRule().evaluate(game) is None


def test_pregame_is_nothing_even_with_scores():
    game = make_game(home_rank=None, away_rank=1, home_score=3, away_score=0, state=GameState.PRE)
    assert UpsetRule().evaluate(game) is None


def test_final_is_confirmed():
    game = make_game(home_rank=None, away_rank=1, home_score=27, away_score=24, state=GameState.POST, completed=True)
    verdict = UpsetRule().evaluate(game)
    assert verdict is not None
    assert verdict.confirmed and not verdict.watch


def test_post_but_not_completed_is_still_a_watch():
    """A suspended game sits in ``post`` without ``completed``; do not call it."""
    game = make_game(home_rank=None, away_rank=1, home_score=27, away_score=24, state=GameState.POST, completed=False)
    verdict = UpsetRule().evaluate(game)
    assert verdict is not None
    assert verdict.watch


def test_rankings_fallback_fills_missing_curated_rank(rankings):
    rule = UpsetRule(rankings)
    assert rule._ranking is not None and rule._ranking.type == "ap"
    # UGA is team 61, AP #1 in the fixture; the scoreboard forgot to say so.
    game = make_game(home_rank=None, away_rank=None, home_score=20, away_score=17, home_id="999", away_id="61")
    verdict = rule.evaluate(game)
    assert verdict is not None
    assert verdict.favorite is game.away
    assert verdict.favorite_rank == 1
    assert verdict.underdog_rank is None


def test_curated_rank_wins_over_poll(rankings):
    rule = UpsetRule(rankings)
    game = make_game(home_rank=None, away_rank=7, home_score=20, away_score=17, home_id="999", away_id="61")
    assert rule.rank_of(game.away) == 7


def test_rank_of_unknown_team_is_none(rankings):
    rule = UpsetRule(rankings)
    game = make_game(home_rank=None, away_rank=None, home_score=20, away_score=17, home_id="999", away_id="998")
    assert rule.rank_of(game.home) is None
    assert rule.evaluate(game) is None


def test_other_poll_can_be_chosen(rankings):
    rule = UpsetRule(rankings, poll="usa")
    assert rule._ranking is not None
    assert rule._ranking.type == "usa"
    missing = UpsetRule(rankings, poll="nope")
    assert missing._ranking is None


def test_set_rankings_none_forgets(rankings):
    rule = UpsetRule(rankings)
    rule.set_rankings(None)
    assert rule._ranking is None
    game = make_game(home_rank=None, away_rank=None, home_score=20, away_score=17, home_id="999", away_id="61")
    assert rule.evaluate(game) is None
